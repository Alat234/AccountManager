import shutil
from pathlib import Path

from storage.constants import BASE_DIR, STATUSES


class FileManager:
    def __init__(self):
        self.setup_directories()

    def setup_directories(self):
        BASE_DIR.mkdir(exist_ok=True)
        for status in STATUSES:
            (BASE_DIR / status).mkdir(exist_ok=True)

    def create_account_folder(self, email, status, password="", api_key="", secret_key="", two_fa="", old_email=""):
        acc_dir = BASE_DIR / status / email
        acc_dir.mkdir(exist_ok=True)
        self.update_info_file(acc_dir, email, old_email, password, api_key, secret_key, two_fa)
        return acc_dir

    def update_info_file(self, acc_dir, email, old_email, password, api_key, secret_key, two_fa):
        info_path = acc_dir / "info.txt"
        with open(info_path, "w", encoding="utf-8") as f:
            f.write(f"Email: {email}\nOld Email: {old_email}\nPassword: {password}\n"
                    f"API Key: {api_key}\nSecret Key: {secret_key}\n2FA Secret: {two_fa}\n")

    def rename_account(self, old_email, new_email, status):
        old_dir = BASE_DIR / status / old_email
        new_dir = BASE_DIR / status / new_email
        if old_dir.exists():
            old_dir.rename(new_dir)
            return new_dir
        return None

    def move_account(self, email, old_status, new_status):
        if old_status == new_status:
            return
        old_dir = BASE_DIR / old_status / email
        new_dir = BASE_DIR / new_status / email
        if old_dir.exists():
            shutil.move(str(old_dir), str(new_dir))

    def delete_account(self, email, status):
        acc_dir = BASE_DIR / status / email
        if acc_dir.exists():
            shutil.rmtree(str(acc_dir))

    def get_account_dir(self, email, status):
        return BASE_DIR / status / email
