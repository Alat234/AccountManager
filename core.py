import sqlite3
import shutil
from pathlib import Path

BASE_DIR = Path("My_Accounts")
STATUS_LIVE = "Живі акаунти"
STATUS_BANNED = "Забанені ф'ючі"
STATUS_LOST = "Дроп загубився"
STATUSES = [STATUS_LIVE, STATUS_BANNED, STATUS_LOST]

class FileManager:
    def __init__(self):
        self.setup_directories()

    def setup_directories(self):
        BASE_DIR.mkdir(exist_ok=True)
        for status in STATUSES:
            (BASE_DIR / status).mkdir(exist_ok=True)

    def create_account_folder(self, email, status, password="", api_key="", secret_key="", old_email=""):
        acc_dir = BASE_DIR / status / email
        acc_dir.mkdir(exist_ok=True)
        self.update_info_file(acc_dir, email, old_email, password, api_key, secret_key)
        return acc_dir

    def update_info_file(self, acc_dir, email, old_email, password, api_key, secret_key):
        """Оновлює або створює файл info.txt"""
        info_path = acc_dir / "info.txt"
        with open(info_path, "w", encoding="utf-8") as f:
            f.write(f"Email: {email}\nOld Email: {old_email}\nPassword: {password}\nAPI Key: {api_key}\nSecret Key: {secret_key}\n")

    def rename_account(self, old_email, new_email, status):
        """Змінює назву папки, якщо змінилася пошта"""
        old_dir = BASE_DIR / status / old_email
        new_dir = BASE_DIR / status / new_email
        if old_dir.exists():
            old_dir.rename(new_dir)
            return new_dir
        return None

    def move_account(self, email, old_status, new_status):
        if old_status == new_status: return
        old_dir = BASE_DIR / old_status / email
        new_dir = BASE_DIR / new_status / email
        if old_dir.exists():
            shutil.move(str(old_dir), str(new_dir))

    def delete_account(self, email, status):
        """Повністю видаляє папку акаунта"""
        acc_dir = BASE_DIR / status / email
        if acc_dir.exists():
            shutil.rmtree(str(acc_dir))

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
                old_email TEXT,
                status TEXT,
                text_notes TEXT,
                invested REAL DEFAULT 0.0,
                deposit REAL DEFAULT 0.0,
                balance REAL DEFAULT 0.0,
                net_profit REAL DEFAULT 0.0
            )
        ''')
        conn.commit()
        conn.close()

    def add_account(self, email, password, api_key, secret_key, old_email, status):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''INSERT INTO accounts (email, password, api_key, secret_key, old_email, status)
                              VALUES (?, ?, ?, ?, ?, ?)''', (email, password, api_key, secret_key, old_email, status))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        finally:
            conn.close()

    def rename_email(self, old_email, new_email):
        """Оновлює головну пошту в БД"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE accounts SET email = ? WHERE email = ?", (new_email, old_email))
        conn.commit()
        conn.close()

    def delete_account(self, email):
        """Видаляє акаунт з БД"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM accounts WHERE email = ?", (email,))
        conn.commit()
        conn.close()