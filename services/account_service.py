from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING

from models.account import (
    ADS_CONFLICT,
    ADS_LINKED,
    ADS_ORPHANED,
    ADS_UNLINKED,
    Account,
)
from storage.constants import BASE_DIR, STATUSES
from storage.database import DatabaseManager
from storage.file_manager import FileManager

if TYPE_CHECKING:
    from clients.adspower import AdsPowerClient

logger = logging.getLogger(__name__)


class AccountService:
    def __init__(self, db: DatabaseManager, fm: FileManager):
        self.db = db
        self.fm = fm

    def get_account(self, email: str):
        return self.db.get_account(email)

    def get_all_accounts(self):
        return self.db.get_all_accounts()

    def get_accounts_summary(self):
        return self.db.get_accounts_summary()

    def get_accounts_for_table(self):
        return self.db.get_accounts_for_table()

    def get_first_email(self):
        return self.db.get_first_email()

    def get_status(self, email: str):
        acc = self.db.get_account(email)
        return acc.status if acc else None

    def create_account(self, email: str):
        status = STATUSES[0]
        self.fm.create_account_folder(email, status)
        self.db.add_account(email, "", "", "", "", "", status)
        return Account(email=email, status=status)

    def save_account(self, account: Account, old_status: str | None = None):
        """Save account data to DB and filesystem.
        If old_status differs from account.status, moves the folder."""
        account.recalculate_profit()

        if old_status and old_status != account.status:
            self.fm.move_account(account.email, old_status, account.status)

        self.db.update_account(account)

        acc_dir = self.fm.get_account_dir(account.email, account.status)
        self.fm.update_info_file(
            acc_dir, account.email, account.old_email,
            account.password, account.api_key, account.secret_key,
            account.two_fa_secret
        )

    def change_status(self, email: str, new_status: str):
        """Move account folder and update DB status. Returns old_status or None on failure."""
        acc = self.db.get_account(email)
        if not acc or acc.status == new_status:
            return None

        old_status = acc.status
        self.fm.move_account(email, old_status, new_status)
        self.db.update_account_status(email, new_status)
        return old_status

    def rename_account(self, old_email: str, new_email: str):
        """Rename account email (= folder name on disk + DB key).
        Returns True on success."""
        acc = self.db.get_account(old_email)
        if not acc:
            return False

        new_dir = BASE_DIR / acc.status / new_email
        if new_dir.exists():
            return False

        result = self.fm.rename_account(old_email, new_email, acc.status)
        if result:
            self.db.rename_email(old_email, new_email)
            return True
        return False

    def delete_account(self, email: str):
        acc = self.db.get_account(email)
        if not acc:
            return False
        self.fm.delete_account(email, acc.status)
        self.db.delete_account(email)
        return True

    def get_account_dir(self, email: str):
        acc = self.db.get_account(email)
        if not acc:
            return None
        return self.fm.get_account_dir(email, acc.status)

    def link_adspower_profile(
        self,
        account: Account,
        profile_id: str,
        *,
        profile_name: str = "",
        serial_number: int = 0,
        remark: str = "",
        event: str = "linked",
    ) -> Account:
        account.ads_profile_id = profile_id
        account.ads_serial_number = int(serial_number) if serial_number else 0
        account.ads_remark = remark or ""
        account.ads_link_status = ADS_LINKED
        account.ads_manual_unlink = False
        account.ads_last_seen_at = self._now()
        account.ads_profile_name = profile_name or account.email
        account.ads_conflict_reason = ""
        self.db.update_account(account)
        self.db.record_ads_link_event(
            account.email,
            profile_id,
            event,
            profile_name=account.ads_profile_name,
        )
        return account

    def unlink_adspower_profile(self, email: str, *, manual: bool = True, note: str = "") -> bool:
        account = self.db.get_account(email)
        if not account or not account.ads_profile_id:
            return False
        previous_profile_id = account.ads_profile_id
        account.ads_link_status = ADS_UNLINKED
        account.ads_manual_unlink = manual
        account.ads_conflict_reason = note
        self.db.update_account(account)
        self.db.record_ads_link_event(
            account.email,
            previous_profile_id,
            "manual_unlinked" if manual else "unlinked",
            profile_name=account.ads_profile_name,
            note=note,
        )
        return True

    # ── AdsPower sync ────────────────────────────────────────

    def sync_with_adspower(self, ads: AdsPowerClient) -> dict:
        """Sync local DB with AdsPower profiles + tags.
        Returns {"created": int, "updated": int, "linked": int, "orphaned": int}.
        """
        remote_tags = ads.list_all_tags()
        if remote_tags:
            self.db.upsert_ads_tags(remote_tags)

        profiles = ads.list_all_profiles()
        logger.info(
            "AdsPower sync fetched profiles=%s tags=%s",
            len(profiles),
            len(remote_tags),
        )
        stats = {
            "fetched": len(profiles),
            "created": 0,
            "updated": 0,
            "linked": 0,
            "renamed": 0,
            "name_conflicts": 0,
            "manual_unlinked": 0,
            "orphaned": 0,
        }
        remote_names = [self._profile_name(p) for p in profiles]
        remote_name_counts = Counter(name for name in remote_names if name)

        remote_ids: set[str] = set()
        for p in profiles:
            pid = p.get("user_id", "")
            if not pid:
                continue
            remote_ids.add(pid)

            name = self._profile_name(p)
            serial = self._profile_serial(p)
            remark = p.get("remark", "") or ""
            tag_ids = p.get("profile_tag_ids") or []
            if isinstance(tag_ids, str):
                tag_ids = [tag_ids] if tag_ids else []

            acc = self.db.get_account_by_profile_id(pid)
            if acc:
                if acc.ads_manual_unlink:
                    stats["manual_unlinked"] += 1
                    logger.info(
                        "AdsPower sync skipped manually unlinked profile=%s account=%s",
                        pid,
                        acc.email,
                    )
                    continue
                if self._mark_name_conflict_if_needed(acc, name, remote_name_counts):
                    stats["name_conflicts"] += 1
                    continue
                if name and name != acc.email and self.rename_account(acc.email, name):
                    logger.info(
                        "Renamed local account from AdsPower profile name: %s -> %s (%s)",
                        acc.email,
                        name,
                        pid,
                    )
                    acc.email = name
                    stats["renamed"] += 1
                self.link_adspower_profile(
                    acc,
                    pid,
                    profile_name=name,
                    serial_number=serial,
                    remark=remark,
                    event="sync_seen",
                )
                self.db.set_account_tags(acc.email, tag_ids)
                stats["updated"] += 1
                continue

            existing = self.db.find_account_by_email_ci(name)
            if existing:
                if existing.ads_manual_unlink:
                    existing.ads_link_status = ADS_CONFLICT
                    existing.ads_conflict_reason = (
                        "Matching AdsPower profile exists, but this account was manually unlinked."
                    )
                    self.db.update_account(existing)
                    stats["manual_unlinked"] += 1
                    logger.warning(
                        "AdsPower sync requires confirmation for manually unlinked account=%s profile=%s",
                        existing.email,
                        pid,
                    )
                    continue
                if existing.ads_profile_id and existing.ads_link_status == ADS_LINKED:
                    existing.ads_link_status = ADS_CONFLICT
                    existing.ads_conflict_reason = (
                        f"AdsPower profile name matches this account, but it is already linked to {existing.ads_profile_id}."
                    )
                    self.db.update_account(existing)
                    stats["name_conflicts"] += 1
                    logger.warning(
                        "AdsPower sync skipped duplicate local account name profile=%s name=%s existing_profile=%s",
                        pid,
                        name,
                        existing.ads_profile_id,
                    )
                    continue
                self.link_adspower_profile(
                    existing,
                    pid,
                    profile_name=name,
                    serial_number=serial,
                    remark=remark,
                    event="sync_auto_linked",
                )
                self.db.set_account_tags(existing.email, tag_ids)
                stats["linked"] += 1
                logger.info("Linked existing account %s to AdsPower profile %s", name, pid)
                continue

            status = STATUSES[0]
            self.fm.create_account_folder(name, status)
            self.db.add_account(
                email=name,
                ads_profile_id=pid,
                ads_serial_number=int(serial) if serial else 0,
                ads_remark=remark,
                ads_link_status=ADS_LINKED,
                ads_last_seen_at=self._now(),
                ads_profile_name=name,
                status=status,
            )
            self.db.record_ads_link_event(name, pid, "sync_created", profile_name=name)
            self.db.set_account_tags(name, tag_ids)
            stats["created"] += 1
            logger.info("Synced new AdsPower profile: %s (%s)", name, pid)

        if remote_ids:
            for account in self.db.get_all_accounts():
                if (
                    account.ads_profile_id
                    and account.ads_link_status == ADS_LINKED
                    and account.ads_profile_id not in remote_ids
                ):
                    account.ads_link_status = ADS_ORPHANED
                    account.ads_conflict_reason = "AdsPower profile was not returned by sync."
                    self.db.update_account(account)
                    self.db.record_ads_link_event(
                        account.email,
                        account.ads_profile_id,
                        "orphaned",
                        profile_name=account.ads_profile_name,
                        note=account.ads_conflict_reason,
                    )
                    stats["orphaned"] += 1
                    logger.warning("Orphaned account (AdsPower profile missing): %s", account.ads_profile_id)

        logger.info("AdsPower sync completed stats=%s", stats)
        return stats

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def _profile_name(profile: dict) -> str:
        return str(profile.get("name") or profile.get("username") or profile.get("user_id", "")).strip()

    @staticmethod
    def _profile_serial(profile: dict) -> int:
        value = profile.get("serial_number") or profile.get("profile_no") or profile.get("serial") or 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _mark_name_conflict_if_needed(
        self,
        account: Account,
        remote_name: str,
        remote_name_counts: Counter,
    ) -> bool:
        if not remote_name or remote_name == account.email:
            account.ads_link_status = ADS_LINKED
            account.ads_conflict_reason = ""
            return False
        target = self.db.find_account_by_email_ci(remote_name)
        if remote_name_counts[remote_name] <= 1 and not target:
            return False
        account.ads_link_status = ADS_CONFLICT
        account.ads_conflict_reason = (
            f"AdsPower profile wants name {remote_name}, but that name is duplicated or already used locally."
        )
        self.db.update_account(account)
        logger.warning(
            "AdsPower sync name conflict profile=%s remote_name=%s local_email=%s duplicate_remote=%s target_exists=%s",
            account.ads_profile_id,
            remote_name,
            account.email,
            remote_name_counts[remote_name] > 1,
            bool(target),
        )
        return True

    def update_remark(self, email: str, remark: str, ads: AdsPowerClient) -> bool:
        acc = self.db.get_account(email)
        if not acc:
            return False
        acc.ads_remark = remark
        self.db.update_account(acc)
        if acc.ads_profile_id:
            ads.update_profile(acc.ads_profile_id, remark=remark)
        return True

    def get_account_tags(self, email: str) -> list[dict]:
        return self.db.get_account_tags(email)
