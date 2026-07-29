from dataclasses import dataclass


@dataclass
class Mailbox:
    email: str
    password: str
    server: str = "imap.gmail.com"
