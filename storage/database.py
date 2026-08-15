import sqlite3
from datetime import datetime

from storage.constants import BASE_DIR, STATUS_BANNED, STATUS_LOST
from models.account import (
    ADS_CONFLICT,
    ADS_LINKED,
    ADS_ORPHANED,
    ADS_UNLINKED,
    Account,
)
from models.mailbox import Mailbox
from models.operation_event import OperationEvent
from models.task import AutomationTask


class DatabaseManager:
    def __init__(self):
        self.db_path = BASE_DIR / "database.db"
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                password TEXT,
                api_key TEXT,
                secret_key TEXT,
                two_fa_secret TEXT,
                old_email TEXT,
                status TEXT,
                text_notes TEXT,
                invested REAL DEFAULT 0.0,
                deposit REAL DEFAULT 0.0,
                balance REAL DEFAULT 0.0,
                net_profit REAL DEFAULT 0.0,
                ads_profile_id TEXT DEFAULT '',
                ads_serial_number INTEGER DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mailboxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                password TEXT,
                server TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS automation_tasks (
                id TEXT PRIMARY KEY,
                account_email TEXT NOT NULL,
                scenario_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                completed_at TEXT,
                result_message TEXT DEFAULT '',
                result_data TEXT DEFAULT '',
                current_step TEXT DEFAULT '',
                last_error TEXT DEFAULT '',
                retry_count INTEGER DEFAULT 0,
                recoverable INTEGER DEFAULT 0,
                requires_user_confirmation INTEGER DEFAULT 0,
                resume_data TEXT DEFAULT '',
                FOREIGN KEY (account_email) REFERENCES accounts(email)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS operation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT DEFAULT '',
                account_email TEXT DEFAULT '',
                event_type TEXT NOT NULL DEFAULT 'general',
                level TEXT NOT NULL DEFAULT 'info',
                title TEXT DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                read_at TEXT,
                data TEXT DEFAULT ''
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ads_tags (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT ''
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS account_ads_tags (
                account_email TEXT NOT NULL,
                tag_id TEXT NOT NULL,
                PRIMARY KEY (account_email, tag_id),
                FOREIGN KEY (account_email) REFERENCES accounts(email),
                FOREIGN KEY (tag_id) REFERENCES ads_tags(id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS account_ads_link_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_email TEXT NOT NULL,
                ads_profile_id TEXT NOT NULL,
                event TEXT NOT NULL,
                profile_name TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        ''')
        self._migrate(conn)
        conn.commit()
        conn.close()

    def _migrate(self, conn):
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(accounts)")
        columns = {row[1] for row in cursor.fetchall()}
        if "ads_profile_id" not in columns:
            cursor.execute("ALTER TABLE accounts ADD COLUMN ads_profile_id TEXT DEFAULT ''")
        if "ads_serial_number" not in columns:
            cursor.execute("ALTER TABLE accounts ADD COLUMN ads_serial_number INTEGER DEFAULT 0")
        if "ads_remark" not in columns:
            cursor.execute("ALTER TABLE accounts ADD COLUMN ads_remark TEXT DEFAULT ''")
        if "ads_link_status" not in columns:
            cursor.execute("ALTER TABLE accounts ADD COLUMN ads_link_status TEXT DEFAULT ''")
            cursor.execute(
                "UPDATE accounts SET ads_link_status = CASE "
                "WHEN ads_profile_id IS NOT NULL AND ads_profile_id != '' THEN ? ELSE ? END",
                (ADS_LINKED, ADS_UNLINKED),
            )
        if "ads_manual_unlink" not in columns:
            cursor.execute("ALTER TABLE accounts ADD COLUMN ads_manual_unlink INTEGER DEFAULT 0")
        if "ads_last_seen_at" not in columns:
            cursor.execute("ALTER TABLE accounts ADD COLUMN ads_last_seen_at TEXT DEFAULT ''")
        if "ads_profile_name" not in columns:
            cursor.execute("ALTER TABLE accounts ADD COLUMN ads_profile_name TEXT DEFAULT ''")
        if "ads_conflict_reason" not in columns:
            cursor.execute("ALTER TABLE accounts ADD COLUMN ads_conflict_reason TEXT DEFAULT ''")

        cursor.execute("PRAGMA table_info(automation_tasks)")
        task_columns = {row[1] for row in cursor.fetchall()}
        if "current_step" not in task_columns:
            cursor.execute("ALTER TABLE automation_tasks ADD COLUMN current_step TEXT DEFAULT ''")
        if "last_error" not in task_columns:
            cursor.execute("ALTER TABLE automation_tasks ADD COLUMN last_error TEXT DEFAULT ''")
        if "retry_count" not in task_columns:
            cursor.execute("ALTER TABLE automation_tasks ADD COLUMN retry_count INTEGER DEFAULT 0")
        if "recoverable" not in task_columns:
            cursor.execute("ALTER TABLE automation_tasks ADD COLUMN recoverable INTEGER DEFAULT 0")
        if "requires_user_confirmation" not in task_columns:
            cursor.execute(
                "ALTER TABLE automation_tasks ADD COLUMN requires_user_confirmation INTEGER DEFAULT 0"
            )
        if "resume_data" not in task_columns:
            cursor.execute("ALTER TABLE automation_tasks ADD COLUMN resume_data TEXT DEFAULT ''")

    # ── Account methods (new, return dataclasses) ──

    def get_account(self, email):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE email=?", (email,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_account(row)

    def get_all_accounts(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts ORDER BY email COLLATE NOCASE")
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_account(r) for r in rows]

    @staticmethod
    def _row_to_account(row) -> Account:
        return Account(
            email=row["email"],
            password=row["password"] or "",
            api_key=row["api_key"] or "",
            secret_key=row["secret_key"] or "",
            two_fa_secret=row["two_fa_secret"] or "",
            old_email=row["old_email"] or "",
            status=row["status"] or "",
            text_notes=row["text_notes"] or "",
            invested=row["invested"] or 0.0,
            deposit=row["deposit"] or 0.0,
            balance=row["balance"] or 0.0,
            net_profit=row["net_profit"] or 0.0,
            ads_profile_id=row["ads_profile_id"] or "",
            ads_serial_number=row["ads_serial_number"] or 0,
            ads_remark=row["ads_remark"] or "",
            ads_link_status=row["ads_link_status"] or ADS_UNLINKED,
            ads_manual_unlink=bool(row["ads_manual_unlink"] or 0),
            ads_last_seen_at=row["ads_last_seen_at"] or "",
            ads_profile_name=row["ads_profile_name"] or "",
            ads_conflict_reason=row["ads_conflict_reason"] or "",
        )

    def get_accounts_summary(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT email, status FROM accounts ORDER BY email COLLATE NOCASE")
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_accounts_for_table(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT email, old_email, password, api_key, net_profit FROM accounts")
        rows = cursor.fetchall()
        conn.close()
        return rows

    def update_account(self, account):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''UPDATE accounts
                          SET password=?, api_key=?, secret_key=?, two_fa_secret=?, old_email=?,
                              status=?, text_notes=?, invested=?, deposit=?, balance=?, net_profit=?,
                              ads_profile_id=?, ads_serial_number=?, ads_remark=?,
                              ads_link_status=?, ads_manual_unlink=?, ads_last_seen_at=?,
                              ads_profile_name=?, ads_conflict_reason=?
                          WHERE email = ?''',
                       (account.password, account.api_key, account.secret_key,
                        account.two_fa_secret, account.old_email, account.status,
                        account.text_notes, account.invested, account.deposit,
                        account.balance, account.net_profit,
                        account.ads_profile_id, account.ads_serial_number,
                        account.ads_remark, account.ads_link_status,
                        1 if account.ads_manual_unlink else 0,
                        account.ads_last_seen_at, account.ads_profile_name,
                        account.ads_conflict_reason,
                        account.email))
        conn.commit()
        conn.close()

    def update_account_status(self, email, new_status):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE accounts SET status=? WHERE email=?", (new_status, email))
        conn.commit()
        conn.close()

    def get_first_email(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT email FROM accounts WHERE status NOT IN (?, ?) ORDER BY email COLLATE NOCASE LIMIT 1",
            (STATUS_BANNED, STATUS_LOST),
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    # ── Legacy account methods (kept for backward compat during migration) ──

    def add_account(self, email, password="", api_key="", secret_key="", two_fa="",
                    old_email="", status="Живі акаунти", ads_profile_id="",
                    ads_serial_number=0, ads_remark="", ads_link_status="",
                    ads_manual_unlink=False, ads_last_seen_at="", ads_profile_name="",
                    ads_conflict_reason=""):
        if not ads_link_status:
            ads_link_status = ADS_LINKED if ads_profile_id else ADS_UNLINKED
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''INSERT INTO accounts
                   (email, password, api_key, secret_key, two_fa_secret, old_email, status,
                    ads_profile_id, ads_serial_number, ads_remark, ads_link_status,
                    ads_manual_unlink, ads_last_seen_at, ads_profile_name, ads_conflict_reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (email, password, api_key, secret_key, two_fa, old_email, status,
                 ads_profile_id, ads_serial_number, ads_remark, ads_link_status,
                 1 if ads_manual_unlink else 0, ads_last_seen_at,
                 ads_profile_name, ads_conflict_reason),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        finally:
            conn.close()

    def rename_email(self, old_email, new_email):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE accounts SET email = ? WHERE email = ?", (new_email, old_email))
        cursor.execute("UPDATE account_ads_tags SET account_email = ? WHERE account_email = ?",
                       (new_email, old_email))
        conn.commit()
        conn.close()

    def delete_account(self, email):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM account_ads_tags WHERE account_email = ?", (email,))
        cursor.execute("DELETE FROM accounts WHERE email = ?", (email,))
        conn.commit()
        conn.close()

    # ── Mailbox methods ──

    def add_mailbox(self, email, password, server):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO mailboxes (email, password, server) VALUES (?, ?, ?)", (email, password, server))
            conn.commit()
        except:
            pass
        finally:
            conn.close()

    def get_mailboxes(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT email, password, server FROM mailboxes")
        res = cursor.fetchall()
        conn.close()
        return res

    def get_mailboxes_as_models(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT email, password, server FROM mailboxes")
        rows = cursor.fetchall()
        conn.close()
        return [Mailbox(email=r[0], password=r[1], server=r[2]) for r in rows]

    def delete_mailbox(self, email):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM mailboxes WHERE email=?", (email,))
        conn.commit()
        conn.close()

    # ── Account lookup by AdsPower profile ──

    def get_account_by_profile_id(self, ads_profile_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE ads_profile_id=?", (ads_profile_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_account(row)

    def get_all_profile_ids(self) -> set[str]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT ads_profile_id FROM accounts WHERE ads_profile_id != ''")
        rows = cursor.fetchall()
        conn.close()
        return {r[0] for r in rows}

    def get_active_profile_ids(self) -> set[str]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ads_profile_id FROM accounts WHERE ads_profile_id != '' AND ads_link_status=?",
            (ADS_LINKED,),
        )
        rows = cursor.fetchall()
        conn.close()
        return {r[0] for r in rows}

    def find_account_by_email_ci(self, email: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE lower(email)=lower(?)", (email,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_account(row)

    def record_ads_link_event(
        self,
        account_email: str,
        ads_profile_id: str,
        event: str,
        *,
        profile_name: str = "",
        note: str = "",
    ) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO account_ads_link_history
               (account_email, ads_profile_id, event, profile_name, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                account_email,
                ads_profile_id,
                event,
                profile_name,
                note,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        conn.close()

    # ── AdsPower tag methods ──

    def upsert_ads_tags(self, tags: list[dict]):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        for t in tags:
            cursor.execute(
                "INSERT OR REPLACE INTO ads_tags (id, name, color) VALUES (?, ?, ?)",
                (t["id"], t["name"], t.get("color", "")),
            )
        conn.commit()
        conn.close()

    def set_account_tags(self, email: str, tag_ids: list[str]):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM account_ads_tags WHERE account_email=?", (email,))
        for tid in tag_ids:
            if not tid:
                continue
            cursor.execute(
                "INSERT OR IGNORE INTO account_ads_tags (account_email, tag_id) VALUES (?, ?)",
                (email, str(tid)),
            )
        conn.commit()
        conn.close()

    def get_account_tags(self, email: str) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                at.tag_id AS id,
                COALESCE(NULLIF(t.name, ''), at.tag_id) AS name,
                COALESCE(t.color, '') AS color
            FROM account_ads_tags at
            LEFT JOIN ads_tags t ON t.id = at.tag_id
            WHERE at.account_email = ?
        """, (email,))
        rows = cursor.fetchall()
        conn.close()
        return [{"id": r["id"], "name": r["name"], "color": r["color"]} for r in rows]

    def get_all_ads_tags(self) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, color FROM ads_tags")
        rows = cursor.fetchall()
        conn.close()
        return [{"id": r["id"], "name": r["name"], "color": r["color"]} for r in rows]

    def get_accounts_with_tags(
        self,
        *,
        archived_only: bool = False,
        include_archive: bool = False,
    ) -> list[tuple]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        sql = "SELECT * FROM accounts"
        params: tuple[str, ...] = ()
        if archived_only:
            sql += " WHERE status IN (?, ?)"
            params = (STATUS_BANNED, STATUS_LOST)
        elif not include_archive:
            sql += " WHERE status NOT IN (?, ?)"
            params = (STATUS_BANNED, STATUS_LOST)
        sql += " ORDER BY email COLLATE NOCASE"
        cursor.execute(sql, params)
        account_rows = cursor.fetchall()
        cursor.execute("""
            SELECT
                at.account_email,
                at.tag_id AS id,
                COALESCE(NULLIF(t.name, ''), at.tag_id) AS name,
                COALESCE(t.color, '') AS color
            FROM account_ads_tags at
            LEFT JOIN ads_tags t ON t.id = at.tag_id
        """)
        tag_rows = cursor.fetchall()
        conn.close()
        from collections import defaultdict
        tags_by_email = defaultdict(list)
        for r in tag_rows:
            tags_by_email[r["account_email"]].append(
                {"id": r["id"], "name": r["name"], "color": r["color"]}
            )
        return [(self._row_to_account(row), tags_by_email.get(row["email"], []))
                for row in account_rows]

    def get_all_accounts_with_tags(self) -> list[tuple]:
        return self.get_accounts_with_tags(include_archive=True)

    def get_ads_accounts_summary(self) -> list[tuple]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT email, status FROM accounts WHERE ads_profile_id != '' ORDER BY email COLLATE NOCASE"
        )
        rows = cursor.fetchall()
        conn.close()
        return rows

    # ── Automation task methods ──

    def add_task(self, task: AutomationTask):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO automation_tasks
               (id, account_email, scenario_type, status, created_at, completed_at,
                result_message, result_data, current_step, last_error, retry_count,
                recoverable, requires_user_confirmation, resume_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (task.id, task.account_email, task.scenario_type, task.status,
             task.created_at.isoformat(), None, task.result_message, task.result_data,
             task.current_step, task.last_error, task.retry_count,
             1 if task.recoverable else 0,
             1 if task.requires_user_confirmation else 0,
             task.resume_data),
        )
        conn.commit()
        conn.close()

    def update_task(self, task: AutomationTask):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            '''UPDATE automation_tasks
               SET status=?, completed_at=?, result_message=?, result_data=?,
                   current_step=?, last_error=?, retry_count=?, recoverable=?,
                   requires_user_confirmation=?, resume_data=?
               WHERE id=?''',
            (task.status,
             task.completed_at.isoformat() if task.completed_at else None,
             task.result_message, task.result_data, task.current_step,
             task.last_error, task.retry_count, 1 if task.recoverable else 0,
             1 if task.requires_user_confirmation else 0, task.resume_data,
             task.id),
        )
        conn.commit()
        conn.close()

    def get_recent_tasks(self, limit: int = 20) -> list[AutomationTask]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM automation_tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()
        from datetime import datetime
        result = []
        for r in rows:
            completed = None
            if r["completed_at"]:
                completed = datetime.fromisoformat(r["completed_at"])
            result.append(AutomationTask(
                id=r["id"],
                account_email=r["account_email"],
                scenario_type=r["scenario_type"],
                status=r["status"],
                created_at=datetime.fromisoformat(r["created_at"]),
                completed_at=completed,
                result_message=r["result_message"] or "",
                result_data=r["result_data"] or "",
                current_step=r["current_step"] or "",
                last_error=r["last_error"] or "",
                retry_count=r["retry_count"] or 0,
                recoverable=bool(r["recoverable"] or 0),
                requires_user_confirmation=bool(r["requires_user_confirmation"] or 0),
                resume_data=r["resume_data"] or "",
            ))
        return result

    # Operation event methods

    def add_operation_event(self, event: OperationEvent) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO operation_events
               (task_id, account_email, event_type, level, title, message,
                created_at, read_at, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                event.task_id,
                event.account_email,
                event.event_type,
                event.level,
                event.title,
                event.message,
                event.created_at.isoformat(),
                event.read_at.isoformat() if event.read_at else None,
                event.data,
            ),
        )
        event_id = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return event_id

    def get_operation_events(
        self,
        *,
        account_email: str = "",
        task_id: str = "",
        limit: int = 100,
    ) -> list[OperationEvent]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        where = []
        params: list[object] = []
        if account_email:
            where.append("account_email = ?")
            params.append(account_email)
        if task_id:
            where.append("task_id = ?")
            params.append(task_id)
        sql = "SELECT * FROM operation_events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        events = []
        for r in rows:
            read_at = datetime.fromisoformat(r["read_at"]) if r["read_at"] else None
            events.append(OperationEvent(
                id=r["id"],
                task_id=r["task_id"] or "",
                account_email=r["account_email"] or "",
                event_type=r["event_type"] or "general",
                level=r["level"] or "info",
                title=r["title"] or "",
                message=r["message"] or "",
                created_at=datetime.fromisoformat(r["created_at"]),
                read_at=read_at,
                data=r["data"] or "",
            ))
        return events

    def prune_operation_events(self, account_email: str, keep: int = 1000) -> None:
        if not account_email:
            return
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            '''
            DELETE FROM operation_events
            WHERE account_email = ?
              AND id NOT IN (
                  SELECT id FROM operation_events
                  WHERE account_email = ?
                  ORDER BY created_at DESC, id DESC
                  LIMIT ?
              )
            ''',
            (account_email, account_email, keep),
        )
        conn.commit()
        conn.close()
