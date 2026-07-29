from storage.database import DatabaseManager
from models.mailbox import Mailbox


class MailboxService:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def add_mailbox(self, email: str, password: str, server: str):
        self.db.add_mailbox(email, password, server)
        return Mailbox(email=email, password=password, server=server)

    def get_all_mailboxes(self):
        return self.db.get_mailboxes_as_models()

    def get_all_mailboxes_raw(self):
        return self.db.get_mailboxes()

    def delete_mailbox(self, email: str):
        self.db.delete_mailbox(email)
