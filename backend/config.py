import os
import pytz

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
