from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from clients.adspower import AdsPowerClient
from clients.icloud_hme import ICloudHMEClient
from models.account import ADS_LINKED
from services.account_service import AccountService
from storage.settings import SettingsManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProfileCreationResult:
    success: bool
    message: str
    email: str = ""
    ads_profile_id: str = ""


ICloudClientFactory = Callable[[AdsPowerClient, str], ICloudHMEClient]


class ProfileCreationService:
    def __init__(
        self,
        account_service: AccountService,
        adspower: AdsPowerClient,
        settings: SettingsManager,
        *,
        icloud_client_factory: ICloudClientFactory = ICloudHMEClient,
    ):
        self.account_service = account_service
        self.adspower = adspower
        self.settings = settings
        self.icloud_client_factory = icloud_client_factory

    def create_with_icloud(
        self,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> ProfileCreationResult:
        icloud_profile_id = (self.settings.get("icloud_ads_profile_id", "") or "").strip()
        if not icloud_profile_id:
            return ProfileCreationResult(
                success=False,
                message="Set iCloud Profile ID in settings first.",
            )

        if not self.adspower.is_running():
            return ProfileCreationResult(success=False, message="AdsPower is not running.")

        logger.info("Creating iCloud HME mask using profile %s", icloud_profile_id)
        try:
            icloud = self.icloud_client_factory(self.adspower, icloud_profile_id)
            if hasattr(icloud, "set_progress_callback"):
                icloud.set_progress_callback(progress_callback)
            label = (self.settings.get("icloud_hme_label", "") or "").strip() or None
            email = icloud.create_mask(label=label)
        except Exception as exc:
            logger.exception("iCloud HME mask creation failed")
            return ProfileCreationResult(success=False, message=f"iCloud HME failed: {exc}")

        return self._create_account_with_ads(email, fallback_to_local=False)

    def create_with_manual_email(self, email: str) -> ProfileCreationResult:
        email = (email or "").strip()
        if not email:
            return ProfileCreationResult(success=False, message="Email is required.")

        return self._create_account_with_ads(email, fallback_to_local=True)

    def _create_account_with_ads(
        self,
        email: str,
        *,
        fallback_to_local: bool,
    ) -> ProfileCreationResult:
        existing = self.account_service.get_account(email)
        if existing:
            if existing.ads_profile_id and existing.ads_link_status == ADS_LINKED:
                return ProfileCreationResult(
                    success=False,
                    message=f"Account already exists and is linked to AdsPower: {email}",
                    email=email,
                    ads_profile_id=existing.ads_profile_id,
                )
            if existing.ads_manual_unlink:
                return ProfileCreationResult(
                    success=False,
                    message=f"Account was manually unlinked from AdsPower. Confirm relink before creating a new profile: {email}",
                    email=email,
                    ads_profile_id=existing.ads_profile_id,
                )
            if self.adspower.is_running():
                profile = self.adspower.find_profile_by_name(email)
                if profile:
                    ads_profile_id = self._extract_profile_id(profile)
                    ads_serial_number = self._extract_serial_number(profile)
                    self.account_service.link_adspower_profile(
                        existing,
                        ads_profile_id,
                        profile_name=email,
                        serial_number=ads_serial_number,
                        remark=profile.get("remark", "") or "",
                        event="create_reused_existing_ads_profile",
                    )
                    return ProfileCreationResult(
                        success=True,
                        message=f"Linked existing AdsPower profile: {email}",
                        email=email,
                        ads_profile_id=ads_profile_id,
                    )
            return ProfileCreationResult(
                success=False,
                message=f"Account already exists: {email}",
                email=email,
                ads_profile_id=existing.ads_profile_id,
            )

        if not self.adspower.is_running():
            if not fallback_to_local:
                return ProfileCreationResult(success=False, message="AdsPower is not running.", email=email)
            account = self.account_service.create_account(email)
            logger.warning("Created local-only account because AdsPower is not running: %s", email)
            return ProfileCreationResult(
                success=True,
                message=f"Created local account without AdsPower profile: {email}",
                email=account.email,
            )

        existing_profile = self.adspower.find_profile_by_name(email)
        if existing_profile:
            ads_profile_id = self._extract_profile_id(existing_profile)
            ads_serial_number = self._extract_serial_number(existing_profile)
            account = self.account_service.create_account(email)
            self.account_service.link_adspower_profile(
                account,
                ads_profile_id,
                profile_name=email,
                serial_number=ads_serial_number,
                remark=existing_profile.get("remark", "") or "",
                event="create_reused_existing_ads_profile",
            )
            logger.info("Created local account %s by reusing AdsPower profile %s", email, ads_profile_id)
            return ProfileCreationResult(
                success=True,
                message=f"Created local account and linked existing AdsPower profile: {email}",
                email=email,
                ads_profile_id=ads_profile_id,
            )

        logger.info("Creating AdsPower profile for %s", email)
        profile = self.adspower.create_profile(
            name=email,
            proxyid="random",
            fingerprint_config={
                "automatic_timezone": 1,
                "random_ua": {
                    "ua_system_version": ["Windows"],
                },
            },
        )
        if not profile:
            if not fallback_to_local:
                return ProfileCreationResult(
                    success=False,
                    message="Failed to create AdsPower profile.",
                    email=email,
                )
            account = self.account_service.create_account(email)
            logger.warning("Created local-only account after AdsPower profile failure: %s", email)
            return ProfileCreationResult(
                success=True,
                message=f"Created local account; AdsPower profile was not created: {email}",
                email=account.email,
            )

        ads_profile_id = self._extract_profile_id(profile)
        ads_serial_number = self._extract_serial_number(profile)
        if not ads_profile_id:
            created_profile = self.adspower.find_profile_by_name(email)
            if created_profile:
                ads_profile_id = self._extract_profile_id(created_profile)
                ads_serial_number = self._extract_serial_number(created_profile)
                profile = created_profile

        if not ads_profile_id:
            if not fallback_to_local:
                return ProfileCreationResult(
                    success=False,
                    message="AdsPower profile was created, but profile ID was not returned.",
                    email=email,
                )
            account = self.account_service.create_account(email)
            logger.warning("Created local-only account because AdsPower profile ID was missing: %s", email)
            return ProfileCreationResult(
                success=True,
                message=f"Created local account; AdsPower profile ID was not returned: {email}",
                email=account.email,
            )

        account = self.account_service.create_account(email)
        self.account_service.link_adspower_profile(
            account,
            ads_profile_id,
            profile_name=email,
            serial_number=ads_serial_number,
            remark=profile.get("remark", "") or "",
            event="created_ads_profile",
        )

        logger.info("Created account %s with AdsPower profile %s", email, account.ads_profile_id)
        return ProfileCreationResult(
            success=True,
            message=f"Created account with AdsPower profile: {email}",
            email=email,
            ads_profile_id=account.ads_profile_id,
        )

    @staticmethod
    def _extract_profile_id(profile: dict) -> str:
        for key in ("id", "user_id", "profile_id"):
            value = profile.get(key)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _extract_serial_number(profile: dict) -> int:
        for key in ("serial_number", "profile_no", "serial"):
            value = profile.get(key)
            if value:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return 0
        return 0
