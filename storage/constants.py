from pathlib import Path

BASE_DIR = Path("My_Accounts")

STATUS_LIVE = "Живі акаунти"
STATUS_BANNED = "Забанені ф'ючі"
STATUS_LOST = "Дроп загубився"
STATUSES = [STATUS_LIVE, STATUS_BANNED, STATUS_LOST]

TAG_SHORT = dict(zip(STATUSES, ["Живий", "Бан ф'юч", "Загубл."]))
SHORT_TO_STATUS = {short: full for full, short in TAG_SHORT.items()}
TAG_VALUES = list(TAG_SHORT.values())
TAG_COLORS = dict(zip(STATUSES, ["#2e7d32", "#8b0000", "#555555"]))

FILTER_ALL = "Всі"

ADS_TAG_COLORS = {
    "darkBlue": "#1565C0",
    "blue": "#42A5F5",
    "purple": "#AB47BC",
    "red": "#EF5350",
    "yellow": "#FFEE58",
    "orange": "#FFA726",
    "green": "#66BB6A",
    "lightGreen": "#9CCC65",
}
ADS_TAG_DEFAULT_COLOR = "#888888"
