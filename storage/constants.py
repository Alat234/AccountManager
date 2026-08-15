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


def normalize_ads_tag_color(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ADS_TAG_DEFAULT_COLOR
    if clean.startswith("#") and len(clean) in (4, 7):
        return clean
    for name, color in ADS_TAG_COLORS.items():
        if clean == name or clean.lower() == name.lower():
            return color
    return ADS_TAG_DEFAULT_COLOR


def readable_text_color(background: str) -> str:
    color = normalize_ads_tag_color(background).lstrip("#")
    if len(color) == 3:
        color = "".join(part * 2 for part in color)
    try:
        red = int(color[0:2], 16)
        green = int(color[2:4], 16)
        blue = int(color[4:6], 16)
    except ValueError:
        return "#ffffff"
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    return "#000000" if luminance > 0.62 else "#ffffff"
