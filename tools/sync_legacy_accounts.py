#!/usr/bin/env python3
"""Merge a legacy My_Accounts.zip into the current AccountsManager data dir.

Default behavior is a dry run. In conflicts, current database values win:
legacy values only fill empty current fields, and conflicts are written to a
masked report.
"""

from __future__ import annotations

import argparse
import gc
import json
import shutil
import sqlite3
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any


CURRENT_ACCOUNT_FIELDS = [
    "password",
    "api_key",
    "secret_key",
    "two_fa_secret",
    "old_email",
    "status",
    "text_notes",
    "invested",
    "deposit",
    "balance",
    "net_profit",
]

LEGACY_ONLY_FIELDS = CURRENT_ACCOUNT_FIELDS + ["tag"]
SECRET_FIELDS = {"password", "api_key", "secret_key", "two_fa_secret"}
ADS_LINKED = "linked"
ADS_UNLINKED = "unlinked"


@dataclass
class AccountPlan:
    action: str
    email: str
    updates: dict[str, Any]
    conflicts: dict[str, dict[str, Any]]


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    current_base = (project_root / args.current_base).resolve()
    current_db = current_base / "database.db"
    report_path = args.report.resolve() if args.report else (
        project_root / "sync_legacy_report.json"
    )

    if not args.old_zip.exists():
        fail(f"Legacy zip not found: {args.old_zip}")
    if not current_db.exists():
        fail(f"Current database not found: {current_db}")
    if not current_base.exists():
        fail(f"Current account base dir not found: {current_base}")

    mode = "apply" if args.apply else "dry-run"
    temp_parent = project_root / "_sync_tmp"
    temp_parent.mkdir(exist_ok=True)
    tmp_path = temp_parent / f"legacy_accounts_{datetime.now():%Y%m%d_%H%M%S}_{id(args)}"
    tmp_path.mkdir(exist_ok=False)
    try:
        legacy_db = extract_legacy_db(args.old_zip, tmp_path)

        current_accounts = load_accounts(current_db)
        legacy_accounts = load_accounts(legacy_db)
        current_mailboxes = load_mailboxes(current_db)
        legacy_mailboxes = load_mailboxes(legacy_db)
        plan = build_plan(current_accounts, legacy_accounts)
        zip_index = build_zip_account_index(args.old_zip)
        file_plan = build_file_plan(
            args.old_zip,
            zip_index,
            legacy_accounts,
            current_base,
            plan,
        )
        mailbox_plan = build_mailbox_plan(current_mailboxes, legacy_mailboxes)

        report = build_report(
            mode,
            current_db,
            args.old_zip,
            current_accounts,
            legacy_accounts,
            plan,
            file_plan,
            mailbox_plan,
        )

        if args.apply:
            backup_dir = create_backup(current_base, current_db, report_path.parent)
            report["backup_dir"] = str(backup_dir)
            apply_database_plan(current_db, plan, mailbox_plan)
            apply_file_plan(args.old_zip, file_plan)
            report["post_apply"] = validate_post_apply(current_db, current_base)

        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print_summary(report, report_path)
    finally:
        cleanup_temp_dir(tmp_path)
        cleanup_empty_dir(temp_parent)

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync legacy My_Accounts.zip into the current My_Accounts directory."
    )
    parser.add_argument("--old-zip", type=Path, required=True, help="Path to legacy My_Accounts.zip")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--current-base", type=Path, default=Path("My_Accounts"))
    parser.add_argument("--report", type=Path, help="Where to write JSON report")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Omit for dry-run.")
    return parser.parse_args()


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(2)


def cleanup_temp_dir(path: Path) -> None:
    gc.collect()
    for attempt in range(15):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == 14:
                print(f"WARNING: could not remove temporary directory: {path}", file=sys.stderr)
                return
            time.sleep(0.2)


def cleanup_empty_dir(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        return


def extract_legacy_db(zip_path: Path, output_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path) as archive:
        matches = [name for name in archive.namelist() if name.replace("\\", "/").endswith("database.db")]
        if not matches:
            fail("Legacy archive does not contain database.db")
        db_member = sorted(matches, key=len)[0]
        target = output_dir / "legacy_database.db"
        with archive.open(db_member) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    return target


def load_accounts(db_path: Path) -> dict[str, dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM accounts WHERE email IS NOT NULL AND email != ''").fetchall()
    return {normalize_email(row["email"]): dict(row) for row in rows}


def load_mailboxes(db_path: Path) -> dict[str, dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mailboxes'"
        ).fetchone()
        if not table_exists:
            return {}
        rows = conn.execute("SELECT * FROM mailboxes WHERE email IS NOT NULL AND email != ''").fetchall()
    return {normalize_email(row["email"]): dict(row) for row in rows}


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def build_plan(
    current_accounts: dict[str, dict[str, Any]],
    legacy_accounts: dict[str, dict[str, Any]],
) -> list[AccountPlan]:
    plans: list[AccountPlan] = []
    for key, legacy in sorted(legacy_accounts.items()):
        email = legacy["email"]
        current = current_accounts.get(key)
        if not current:
            plans.append(AccountPlan("insert_account", email, normalize_insert_values(legacy), {}))
            continue

        updates: dict[str, Any] = {}
        conflicts: dict[str, dict[str, Any]] = {}
        for field in LEGACY_ONLY_FIELDS:
            if field not in legacy or field not in current:
                continue
            legacy_value = clean_value(legacy.get(field))
            current_value = clean_value(current.get(field))
            if is_empty(current_value) and not is_empty(legacy_value):
                updates[field] = legacy_value
            elif (
                not is_empty(current_value)
                and not is_empty(legacy_value)
                and current_value != legacy_value
            ):
                conflicts[field] = {
                    "kept": mask_value(field, current_value),
                    "legacy_ignored": mask_value(field, legacy_value),
                    "reason": "current_value_wins",
                }

        if updates or conflicts:
            plans.append(AccountPlan("update_existing", email, updates, conflicts))

    return plans


def normalize_insert_values(legacy: dict[str, Any]) -> dict[str, Any]:
    values = {field: clean_value(legacy.get(field)) for field in CURRENT_ACCOUNT_FIELDS}
    values["email"] = clean_value(legacy.get("email"))
    values["tag"] = clean_value(legacy.get("tag"))
    values["ads_profile_id"] = ""
    values["ads_serial_number"] = 0
    values["ads_remark"] = ""
    values["ads_link_status"] = ADS_UNLINKED
    values["ads_manual_unlink"] = 0
    values["ads_last_seen_at"] = ""
    values["ads_profile_name"] = ""
    values["ads_conflict_reason"] = ""
    return values


def clean_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return value


def is_empty(value: Any) -> bool:
    return value is None or value == ""


def mask_value(field: str, value: Any) -> Any:
    if field in SECRET_FIELDS and not is_empty(value):
        return "***"
    return value


def build_zip_account_index(zip_path: Path) -> dict[str, list[zipfile.ZipInfo]]:
    index: dict[str, list[zipfile.ZipInfo]] = {}
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            path = PurePosixPath(info.filename.replace("\\", "/"))
            parts = path.parts
            if len(parts) < 4 or parts[0] != "My_Accounts":
                continue
            email = parts[2]
            if "@" not in email and email not in {"random", "idcloud"}:
                continue
            index.setdefault(normalize_email(email), []).append(info)
    return index


def build_file_plan(
    zip_path: Path,
    zip_index: dict[str, list[zipfile.ZipInfo]],
    legacy_accounts: dict[str, dict[str, Any]],
    current_base: Path,
    account_plan: list[AccountPlan],
) -> list[dict[str, Any]]:
    planned_emails = {
        normalize_email(item.email)
        for item in account_plan
        if item.action in {"insert_account", "update_existing"}
    }
    results: list[dict[str, Any]] = []
    for key in sorted(planned_emails):
        legacy = legacy_accounts.get(key)
        entries = zip_index.get(key, [])
        if not legacy or not entries:
            if legacy:
                results.append({
                    "email": legacy["email"],
                    "action": "missing_legacy_files",
                    "files": 0,
                })
            continue
        status = clean_value(legacy.get("status"))
        target_dir = current_base / status / legacy["email"]
        for entry in entries:
            rel_parts = PurePosixPath(entry.filename.replace("\\", "/")).parts[3:]
            if not rel_parts:
                continue
            target_path = target_dir.joinpath(*rel_parts)
            final_path, action = resolve_file_target(target_path)
            results.append({
                "email": legacy["email"],
                "zip_member": entry.filename,
                "target": str(final_path),
                "action": action,
                "size": entry.file_size,
            })
    return results


def resolve_file_target(target_path: Path) -> tuple[Path, str]:
    if not target_path.exists():
        return target_path, "copy_new"
    suffix = target_path.suffix
    stem = target_path.stem
    candidate = target_path.with_name(f"{stem}.legacy_{datetime.now():%Y%m%d_%H%M%S}{suffix}")
    counter = 2
    while candidate.exists():
        candidate = target_path.with_name(
            f"{stem}.legacy_{datetime.now():%Y%m%d_%H%M%S}_{counter}{suffix}"
        )
        counter += 1
    return candidate, "copy_renamed_collision"


def build_mailbox_plan(
    current_mailboxes: dict[str, dict[str, Any]],
    legacy_mailboxes: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for key, legacy in sorted(legacy_mailboxes.items()):
        current = current_mailboxes.get(key)
        if not current:
            plan.append({
                "action": "insert_mailbox",
                "email": legacy["email"],
                "password": clean_value(legacy.get("password")),
                "server": clean_value(legacy.get("server")),
            })
            continue
        updates = {}
        conflicts = {}
        for field in ("password", "server"):
            legacy_value = clean_value(legacy.get(field))
            current_value = clean_value(current.get(field))
            if is_empty(current_value) and not is_empty(legacy_value):
                updates[field] = legacy_value
            elif (
                not is_empty(current_value)
                and not is_empty(legacy_value)
                and current_value != legacy_value
            ):
                conflicts[field] = {
                    "kept": mask_value(field, current_value),
                    "legacy_ignored": mask_value(field, legacy_value),
                    "reason": "current_value_wins",
                }
        if updates or conflicts:
            plan.append({
                "action": "update_mailbox",
                "email": legacy["email"],
                "updates": updates,
                "conflicts": conflicts,
            })
    return plan


def build_report(
    mode: str,
    current_db: Path,
    old_zip: Path,
    current_accounts: dict[str, dict[str, Any]],
    legacy_accounts: dict[str, dict[str, Any]],
    plan: list[AccountPlan],
    file_plan: list[dict[str, Any]],
    mailbox_plan: list[dict[str, Any]],
) -> dict[str, Any]:
    current_keys = set(current_accounts)
    legacy_keys = set(legacy_accounts)
    account_actions = [p.action for p in plan]
    conflicts = [
        {"email": p.email, "fields": p.conflicts}
        for p in plan
        if p.conflicts
    ]
    report_plan = [
        {
            "action": p.action,
            "email": p.email,
            "updates": {k: mask_value(k, v) for k, v in p.updates.items()},
            "conflicts": p.conflicts,
        }
        for p in plan
    ]
    return {
        "mode": mode,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "current_db": str(current_db),
        "old_zip": str(old_zip),
        "summary": {
            "legacy_accounts": len(legacy_accounts),
            "current_accounts": len(current_accounts),
            "overlap": len(current_keys & legacy_keys),
            "legacy_only": len(legacy_keys - current_keys),
            "current_only": len(current_keys - legacy_keys),
            "accounts_to_insert": account_actions.count("insert_account"),
            "accounts_to_update": account_actions.count("update_existing"),
            "accounts_with_conflicts": len(conflicts),
            "files_to_copy": sum(1 for item in file_plan if item.get("action", "").startswith("copy")),
            "file_collisions": sum(1 for item in file_plan if item.get("action") == "copy_renamed_collision"),
            "mailboxes_to_insert": sum(1 for item in mailbox_plan if item["action"] == "insert_mailbox"),
            "mailboxes_to_update": sum(1 for item in mailbox_plan if item["action"] == "update_mailbox"),
        },
        "policy": {
            "conflicts": "current database wins; legacy values are ignored",
            "empty_current_fields": "filled from legacy values",
            "old_only_accounts": "inserted as ads_link_status=unlinked",
            "current_only_accounts": "left unchanged",
            "file_collisions": "legacy file copied with .legacy_YYYYMMDD_HHMMSS suffix",
        },
        "account_plan": report_plan,
        "account_conflicts": conflicts,
        "mailbox_plan": [
            redact_mailbox_plan(item)
            for item in mailbox_plan
        ],
        "file_plan": file_plan,
    }


def redact_mailbox_plan(item: dict[str, Any]) -> dict[str, Any]:
    clone = dict(item)
    if "password" in clone and clone["password"]:
        clone["password"] = "***"
    if "updates" in clone:
        clone["updates"] = {
            key: mask_value(key, value)
            for key, value in clone["updates"].items()
        }
    return clone


def create_backup(current_base: Path, current_db: Path, output_dir: Path) -> Path:
    backup_dir = output_dir / f"legacy_sync_backup_{datetime.now():%Y%m%d_%H%M%S}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(current_db, backup_dir / "database.db")

    manifest = []
    for status_dir in current_base.iterdir():
        if not status_dir.is_dir():
            continue
        manifest.append(str(status_dir.relative_to(current_base)))
    (backup_dir / "manifest.json").write_text(
        json.dumps({"status_dirs": manifest}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return backup_dir


def apply_database_plan(
    current_db: Path,
    account_plan: list[AccountPlan],
    mailbox_plan: list[dict[str, Any]],
) -> None:
    with sqlite3.connect(current_db) as conn:
        ensure_audit_table(conn)
        account_columns = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
        for item in account_plan:
            if item.action == "insert_account":
                insert_account(conn, account_columns, item.updates)
                record_audit(conn, item.email, "insert_account", item)
            elif item.action == "update_existing" and item.updates:
                update_account(conn, account_columns, item.email, item.updates)
                record_audit(conn, item.email, "update_existing", item)
            elif item.conflicts:
                record_audit(conn, item.email, "conflict_ignored", item)

        for item in mailbox_plan:
            if item["action"] == "insert_mailbox":
                conn.execute(
                    "INSERT OR IGNORE INTO mailboxes (email, password, server) VALUES (?, ?, ?)",
                    (item["email"], item.get("password", ""), item.get("server", "")),
                )
            elif item["action"] == "update_mailbox" and item.get("updates"):
                fields = sorted(item["updates"])
                assignments = ", ".join(f"{field}=?" for field in fields)
                params = [item["updates"][field] for field in fields] + [item["email"]]
                conn.execute(f"UPDATE mailboxes SET {assignments} WHERE lower(email)=lower(?)", params)
        conn.commit()


def ensure_audit_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS legacy_import_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_email TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            data TEXT NOT NULL DEFAULT ''
        )
        """
    )


def insert_account(conn: sqlite3.Connection, account_columns: set[str], values: dict[str, Any]) -> None:
    usable = {
        key: value
        for key, value in values.items()
        if key in account_columns and key != "id"
    }
    fields = sorted(usable)
    placeholders = ", ".join("?" for _ in fields)
    sql = f"INSERT OR IGNORE INTO accounts ({', '.join(fields)}) VALUES ({placeholders})"
    conn.execute(sql, [usable[field] for field in fields])


def update_account(
    conn: sqlite3.Connection,
    account_columns: set[str],
    email: str,
    updates: dict[str, Any],
) -> None:
    usable = {
        key: value
        for key, value in updates.items()
        if key in account_columns and key not in {"id", "email"}
    }
    if not usable:
        return
    fields = sorted(usable)
    assignments = ", ".join(f"{field}=?" for field in fields)
    params = [usable[field] for field in fields] + [email]
    conn.execute(f"UPDATE accounts SET {assignments} WHERE lower(email)=lower(?)", params)


def record_audit(conn: sqlite3.Connection, email: str, event_type: str, item: AccountPlan) -> None:
    data = {
        "action": item.action,
        "updates": {k: mask_value(k, v) for k, v in item.updates.items()},
        "conflicts": item.conflicts,
    }
    conn.execute(
        """
        INSERT INTO legacy_import_events (account_email, event_type, created_at, data)
        VALUES (?, ?, ?, ?)
        """,
        (email, event_type, datetime.now().isoformat(timespec="seconds"), json.dumps(data, ensure_ascii=False)),
    )


def apply_file_plan(zip_path: Path, file_plan: list[dict[str, Any]]) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        for item in file_plan:
            if not item.get("action", "").startswith("copy"):
                continue
            target = Path(item["target"])
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item["zip_member"]) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def validate_post_apply(current_db: Path, current_base: Path) -> dict[str, Any]:
    with sqlite3.connect(current_db) as conn:
        account_count = conn.execute("SELECT count(*) FROM accounts").fetchone()[0]
        duplicate_emails = conn.execute(
            """
            SELECT lower(email), count(*)
            FROM accounts
            WHERE email IS NOT NULL AND email != ''
            GROUP BY lower(email)
            HAVING count(*) > 1
            """
        ).fetchall()
        linked_profiles = conn.execute(
            "SELECT count(*) FROM accounts WHERE coalesce(ads_profile_id, '') != ''"
        ).fetchone()[0]
    return {
        "account_count": account_count,
        "linked_profiles": linked_profiles,
        "duplicate_email_count": len(duplicate_emails),
        "current_base_exists": current_base.exists(),
    }


def print_summary(report: dict[str, Any], report_path: Path) -> None:
    summary = report["summary"]
    print(f"mode: {report['mode']}")
    print(f"legacy_accounts: {summary['legacy_accounts']}")
    print(f"current_accounts: {summary['current_accounts']}")
    print(f"overlap: {summary['overlap']}")
    print(f"accounts_to_insert: {summary['accounts_to_insert']}")
    print(f"accounts_to_update: {summary['accounts_to_update']}")
    print(f"accounts_with_conflicts: {summary['accounts_with_conflicts']}")
    print(f"files_to_copy: {summary['files_to_copy']}")
    print(f"file_collisions: {summary['file_collisions']}")
    print(f"report: {report_path}")


if __name__ == "__main__":
    raise SystemExit(main())
