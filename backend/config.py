import os
import pytz
from datetime import datetime

TEST_MODE = False

MATCH_CODE_OFFSET = 1181

ESPN_SERIES_ID = 8048
ESPN_IPL_SERIES_ID = 1510719
ESPN_IPL_SERIES_SLUG = "ipl-2026"
ESPN_MATCH_ID_OFFSET = 1527673
CRICBUZZ_IPL_SERIES_ID = 9241
CRICBUZZ_IPL_SERIES_SLUG = "indian-premier-league-2026"

ROLES = ["Wicketkeeper", "Batter", "AllRounder", "Bowler"]

SECRET_KEY = os.environ.get("SECRET_KEY", "fantasy-cricket-dev-secret-key")

IST = pytz.timezone("Asia/Kolkata")

APP_CURRENT_DATE = os.environ.get("APP_CURRENT_DATE", "").strip()
APP_CURRENT_TIME = os.environ.get("APP_CURRENT_TIME", "").strip()
APP_CURRENT_DATETIME = os.environ.get("APP_CURRENT_DATETIME", "").strip()

TEAM_MAP = {
    "Royal Challengers Bengaluru": "RCB",
    "Mumbai Indians": "MI",
    "Chennai Super Kings": "CSK",
    "Kolkata Knight Riders": "KKR",
    "Rajasthan Royals": "RR",
    "Gujarat Titans": "GT",
    "Delhi Capitals": "DC",
    "Lucknow Super Giants": "LSG",
    "Punjab Kings": "PBKS",
    "Sunrisers Hyderabad": "SRH",
    "RCB": "RCB", "MI": "MI", "CSK": "CSK", "KKR": "KKR", "RR": "RR",
    "GT": "GT", "DC": "DC", "LSG": "LSG", "PBKS": "PBKS", "SRH": "SRH",
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "fantasy.db")
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")


def _parse_app_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None

    candidates = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
    ]
    for fmt in candidates:
        try:
            parsed = datetime.strptime(value, fmt)
            return IST.localize(parsed)
        except Exception:
            continue
    return None


def get_current_datetime() -> datetime:
    """Return the app's notion of now, honoring local test overrides."""
    if APP_CURRENT_DATETIME:
        parsed = _parse_app_datetime(APP_CURRENT_DATETIME)
        if parsed:
            return parsed

    if APP_CURRENT_DATE and APP_CURRENT_TIME:
        parsed = _parse_app_datetime(f"{APP_CURRENT_DATE} {APP_CURRENT_TIME}")
        if parsed:
            return parsed

    now = datetime.now(IST)
    return now


def get_current_date_key() -> str:
    return get_current_datetime().strftime("%Y-%m-%d")


def is_current_datetime_overridden() -> bool:
    return bool(APP_CURRENT_DATETIME or (APP_CURRENT_DATE and APP_CURRENT_TIME))
