from dataclasses import dataclass, field


ADS_LINKED = "linked"
ADS_UNLINKED = "unlinked"
ADS_ORPHANED = "orphaned"
ADS_CONFLICT = "conflict"


@dataclass
class Account:
    email: str
    password: str = ""
    api_key: str = ""
    secret_key: str = ""
    two_fa_secret: str = ""
    old_email: str = ""
    status: str = "Живі акаунти"
    text_notes: str = ""
    invested: float = 0.0
    deposit: float = 0.0
    balance: float = 0.0
    net_profit: float = 0.0
    ads_profile_id: str = ""
    ads_serial_number: int = 0
    ads_remark: str = ""
    ads_link_status: str = ADS_UNLINKED
    ads_manual_unlink: bool = False
    ads_last_seen_at: str = ""
    ads_profile_name: str = ""
    ads_conflict_reason: str = ""
    ads_tag_ids: list[str] = field(default_factory=list)

    def recalculate_profit(self):
        self.net_profit = self.balance - self.deposit - self.invested
