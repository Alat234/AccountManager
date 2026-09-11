"""MEXC RK category names observed in the 2026-09-07 form."""

ADDRESS_DOCUMENT_TYPES = (
    "Utility Bills (Water, Electricity, Gas, Internet)",
    "Bank, Credit Card & Financial Statements",
    "Government Documents (Tax, Residence)",
    "Mobile Bills, Insurance & Other Valid Documents",
    "Other Document",
)
DEPOSIT_SOURCE_TYPES = (
    "Funds From Personal Wallet or Trading Platform",
    "Funds From Third-Party Transfers",
    "Funds From Crypto Investments",
    "Funds From Investment Returns on Another Platform",
    "Other Special Circumstances",
)
DEFAULT_ADDRESS_TYPE = ADDRESS_DOCUMENT_TYPES[1]
DEFAULT_DEPOSIT_SOURCE_TYPE = DEPOSIT_SOURCE_TYPES[0]


def normalized_category(value, choices: tuple[str, ...], default: str) -> str:
    """Repair legacy free-text settings while retaining supported selections."""
    normalized = str(value or "").strip().casefold()
    return next((item for item in choices if item.casefold() == normalized), default)
