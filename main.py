# =============================
# IMPORTS
# =============================
import sys
print("🔥 STARTING APP", flush=True)
sys.stdout.flush()

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import pytz
from typing import Optional
from bs4 import BeautifulSoup
import requests
import time
import re
import threading
import os
import json
import traceback

try:
    print("🔥 inside try block")

    # =============================
    # CONFIG
    # =============================
    TEST_MODE = True
    TEST_MODE_MONTH = 3
    TEST_MODE_DATE = 22
    TEST_MODE_TIME_HR = 20
    TEST_MODE_TIME_MIN = 0
    
    MATCH_CODE_OFFSET = 1107 if TEST_MODE else 1181
    
    ROLES = ["Wicketkeeper", "Batter", "AllRounder", "Bowler"]
    
    app = FastAPI()
    
    # Add session middleware
    app.add_middleware(SessionMiddleware, secret_key="your-secret-key-here")  # Change to a secure key
    
    # =============================
    # CACHE
    # =============================
    CACHE = {
        "players": None,
        "users": None,
        "matches": None,
        "last_updated": 0
    }
    CACHE_TTL = 60
    
    # =============================
    # GOOGLE SHEETS
    # =============================
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if not creds_json:
            raise RuntimeError("GOOGLE_CREDENTIALS env var is required")
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    except Exception as e:
        print("❌ creds failed")
        traceback.print_exc()
    
    
    
    client = gspread.authorize(creds)
    if (TEST_MODE):
        sheet = client.open("FantasyCricket2025")
    else:
        sheet = client.open("FantasyCricket")
    
    users_sheet = sheet.worksheet("Users")
    players_sheet = sheet.worksheet("Players")
    matches_sheet = sheet.worksheet("Matches")
    teams_sheet = sheet.worksheet("Teams")
    
    # =============================
    # TIMEZONE
    # =============================
    ist = pytz.timezone("Asia/Kolkata")
    
    # =============================
    # TEAM MAP (UNCHANGED)
    # =============================
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
        "RCB": "RCB",
        "MI": "MI",
        "CSK": "CSK",
        "KKR": "KKR",
        "RR": "RR",
        "GT": "GT",
        "DC": "DC",
        "LSG": "LSG",
        "PBKS": "PBKS",
        "SRH": "SRH"
    }
    
    # =============================
    # HELPERS (UNCHANGED LOGIC)
    # =============================
    def normalize_name(name):
        return name.lower().replace(".", "").strip()
    
    def clean_name(name):
        return re.sub(r"[†*]", "", name).strip()
    
    def clean_team_name(name):
        # Remove anything in parentheses
        name = re.sub(r"\(.*?\)", "", name).strip()
    
        # Normalize spacing
        name = " ".join(name.split())
    
        # Convert to short name using TEAM_MAP
        short = TEAM_MAP.get(name)
    
        if not short:
            print("❌ Team mapping missing for:", name)
            return name  # fallback (important for debugging)
    
        return short
    
    def is_batting_role(role):
        return role in ["Batter", "Wicketkeeper", "AllRounder"]
    
    def build_player_role_map(players_data):
        role_map = {}
        for p in players_data:
            role_map[int(p["PlayerID"])] = p["Role"]
        return role_map
    
    def build_player_lookup(players):
        lookup = {}
    
        for p in players:
            team = p["Team"]
            pid = p["PlayerID"]
    
            names = [p["Name"]]
    
            if p.get("Aliases"):
                names.extend(p["Aliases"].split(","))
    
            for name in names:
                key = (normalize_name(name), team)
                lookup[key] = pid
    
        return lookup
    
    def get_player_id_from_lookup(name, team, lookup):
        return lookup.get((normalize_name(name), team))

    def render_page(title, body, extra_head="", page_class=""):
        page_class_attr = f" {page_class}" if page_class else ""
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
            <title>{title}</title>
            <style>
                :root {{
                    --bg: #f4f6fb;
                    --card: #ffffff;
                    --text: #172033;
                    --muted: #61708a;
                    --border: #dbe2ef;
                    --shadow: 0 18px 48px rgba(21, 31, 56, 0.08);
                    --primary: #1d4ed8;
                    --primary-dark: #1e40af;
                    --success: #16803c;
                    --warning: #d97706;
                    --danger: #c62828;
                    --secondary: #5b6474;
                    --highlight: #fff3cd;
                }}
                * {{
                    box-sizing: border-box;
                }}
                body {{
                    margin: 0;
                    font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
                    background:
                        radial-gradient(circle at top, rgba(29, 78, 216, 0.08), transparent 28%),
                        linear-gradient(180deg, #f8faff 0%, var(--bg) 100%);
                    color: var(--text);
                }}
                .page-shell {{
                    width: min(1100px, 100%);
                    margin: 0 auto;
                    padding: 20px 16px 40px;
                }}
                .page-card {{
                    background: var(--card);
                    border: 1px solid rgba(219, 226, 239, 0.95);
                    border-radius: 20px;
                    box-shadow: var(--shadow);
                    padding: 22px;
                }}
                h1, h2, h3 {{
                    margin: 0 0 12px;
                    line-height: 1.2;
                }}
                p {{
                    margin: 0 0 12px;
                }}
                .muted {{
                    color: var(--muted);
                }}
                .message {{
                    margin-bottom: 16px;
                    padding: 12px 14px;
                    border-radius: 12px;
                    font-size: 0.95rem;
                }}
                .message.error {{
                    background: #fdecec;
                    color: #9f1d1d;
                    border: 1px solid #f3c5c5;
                }}
                .message.success {{
                    background: #ebf8ee;
                    color: #136132;
                    border: 1px solid #bfe0ca;
                }}
                .form-grid {{
                    display: grid;
                    gap: 14px;
                }}
                label {{
                    display: block;
                    font-size: 0.95rem;
                    font-weight: 600;
                    margin-bottom: 6px;
                }}
                input[type="text"],
                input[type="password"] {{
                    width: 100%;
                    min-height: 46px;
                    padding: 11px 13px;
                    border: 1px solid var(--border);
                    border-radius: 12px;
                    font-size: 16px;
                    background: #fff;
                }}
                input[type="text"]:focus,
                input[type="password"]:focus {{
                    outline: 2px solid rgba(29, 78, 216, 0.14);
                    border-color: var(--primary);
                }}
                .button-row {{
                    display: flex;
                    flex-wrap: wrap;
                    gap: 10px;
                    margin-top: 8px;
                }}
                .btn,
                button {{
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 8px;
                    width: fit-content;
                    min-height: 44px;
                    padding: 10px 14px;
                    border: 0;
                    border-radius: 12px;
                    color: #fff;
                    text-decoration: none;
                    font-weight: 600;
                    font-size: 0.95rem;
                    cursor: pointer;
                }}
                .btn:disabled,
                button:disabled {{
                    opacity: 0.7;
                    cursor: wait;
                }}
                .btn-primary {{ background: var(--primary); }}
                .btn-primary:hover {{ background: var(--primary-dark); }}
                .btn-success {{ background: var(--success); }}
                .btn-warning {{ background: var(--warning); }}
                .btn-danger {{ background: var(--danger); }}
                .btn-secondary {{ background: var(--secondary); }}
                .back-link {{
                    display: inline-flex;
                    margin-top: 18px;
                    color: var(--primary-dark);
                    text-decoration: none;
                    font-weight: 600;
                }}
                .match-list,
                .actions-grid,
                .score-layout {{
                    display: grid;
                    gap: 14px;
                }}
                .actions-grid {{
                    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
                    margin-bottom: 18px;
                }}
                .action-card,
                .match-card,
                .panel-card {{
                    border: 1px solid var(--border);
                    border-radius: 16px;
                    background: #fff;
                    padding: 16px;
                }}
                .match-card {{
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 14px;
                }}
                .match-meta {{
                    display: grid;
                    gap: 6px;
                }}
                .kicker {{
                    font-size: 0.83rem;
                    text-transform: uppercase;
                    letter-spacing: 0.08em;
                    color: var(--muted);
                }}
                .table-scroll {{
                    overflow-x: auto;
                    -webkit-overflow-scrolling: touch;
                    border: 1px solid var(--border);
                    border-radius: 14px;
                    background: #fff;
                }}
                .table-scroll table {{
                    width: 100%;
                    min-width: 100%;
                    border-collapse: collapse;
                }}
                .table-scroll th,
                .table-scroll td {{
                    border-bottom: 1px solid #e8edf5;
                    padding: 10px 12px;
                    text-align: left;
                    white-space: nowrap;
                    font-size: 0.94rem;
                }}
                .table-scroll th {{
                    background: #f6f8fc;
                }}
                .table-scroll tr:last-child td {{
                    border-bottom: 0;
                }}
                .user-team,
                .current-user-row,
                .current-user-column {{
                    background: var(--highlight);
                    font-weight: 700;
                }}
                .selection-summary {{
                    margin-bottom: 14px;
                    color: var(--muted);
                    font-weight: 600;
                }}
                .team-section {{
                    margin-top: 18px;
                }}
                .team-section h3 {{
                    margin-bottom: 10px;
                }}
                .compact-note {{
                    margin-bottom: 12px;
                    color: var(--muted);
                    font-size: 0.92rem;
                }}
                @media (max-width: 720px) {{
                    .page-shell {{
                        padding: 14px 12px 28px;
                    }}
                    .page-card {{
                        border-radius: 16px;
                        padding: 16px;
                    }}
                    .actions-grid {{
                        grid-template-columns: 1fr;
                    }}
                    .match-card {{
                        flex-direction: column;
                        align-items: stretch;
                    }}
                    .match-card .btn {{
                        width: 100%;
                    }}
                    .score-layout {{
                        grid-template-columns: 1fr;
                    }}
                    .table-scroll th,
                    .table-scroll td {{
                        padding: 9px 10px;
                        font-size: 0.88rem;
                    }}
                    .btn,
                    button {{
                        width: 100%;
                    }}
                    .button-row .btn,
                    .button-row button {{
                        flex: 1 1 100%;
                    }}
                }}
                @media (min-width: 721px) {{
                    .score-layout {{
                        grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
                    }}
                }}
            </style>
            {extra_head}
        </head>
        <body>
            <main class="page-shell{page_class_attr}">
                <section class="page-card">
                    {body}
                </section>
            </main>
        </body>
        </html>
        """
    
    # =============================
    # CACHE FETCH
    # =============================
    def get_cached_data(sheet_name):
        now = time.time()
    
        if now - CACHE["last_updated"] > CACHE_TTL:
            CACHE["players"] = players_sheet.get_all_records()
            CACHE["users"] = users_sheet.get_all_records()
            CACHE["matches"] = matches_sheet.get_all_records()
            CACHE["last_updated"] = now
    
        return CACHE[sheet_name]

    def get_player_total_points():
        totals = {}

        try:
            points_rows = sheet.worksheet("PlayerPoints").get_all_records()
        except Exception:
            return totals

        for row in points_rows:
            player_id = str(row.get("PlayerID", "")).strip()
            if not player_id:
                continue

            try:
                points = float(row.get("Points", 0) or 0)
            except (TypeError, ValueError):
                points = 0

            totals[player_id] = totals.get(player_id, 0) + points

        return totals
    
    # =============================
    # MATCH LOCK LOGIC (UNCHANGED)
    # =============================
    def is_match_locked_by_row(match):
        try:
            match_datetime = datetime.strptime(
                f"{match['Date']} {match['Time']}",
                "%Y-%m-%d %H:%M"
            )
            match_datetime = ist.localize(match_datetime)
        except:
            return False
    
        if TEST_MODE:
            now = ist.localize(datetime(
                2025,
                TEST_MODE_MONTH,
                TEST_MODE_DATE,
                TEST_MODE_TIME_HR,
                TEST_MODE_TIME_MIN
            ))
        else:
            now = datetime.now(ist)
    
        return now >= match_datetime
    
    # Backward compatibility for older call-sites
    def is_match_locked(match_datetime_str):
        # expected format: "YYYY-MM-DD HH:MM"
        try:
            match_datetime = datetime.strptime(match_datetime_str, "%Y-%m-%d %H:%M")
            match_datetime = ist.localize(match_datetime)
        except Exception:
            return False
    
        if TEST_MODE:
            now = ist.localize(datetime(
                2025,
                TEST_MODE_MONTH,
                TEST_MODE_DATE,
                TEST_MODE_TIME_HR,
                TEST_MODE_TIME_MIN
            ))
        else:
            now = datetime.now(ist)
    
        return now >= match_datetime
    
    # =============================
    # FETCH SCORECARD
    # =============================
    def fetch_scorecard_html(match_code):
        url = f"https://www.howstat.com/Cricket/Statistics/IPL/MatchScorecard.asp?MatchCode={match_code}"
    
        try:
            res = requests.get(url)
            if res.status_code != 200:
                return None
            return res.text
        except Exception as e:
            print("Error fetching scorecard:", e)
            return None
            
    # =============================
    # PLAYER MODEL
    # =============================
    class Player:
        def __init__(self, player_id, name):
            self.player_id = player_id
            self.name = name
            self.team = None
    
            # Batting
            self.runs = 0
            self.balls = 0
            self.fours = 0
            self.sixes = 0
            self.strike_rate = 0.0
            self.dismissal = None
            self.is_out = False
    
            # Bowling
            self.overs = 0.0
            self.maidens = 0
            self.runs_conceded = 0
            self.wickets = 0
            self.bowled = 0
            self.lbw = 0
            self.economy = 0.0
    
            # Fielding
            self.catches = 0
            self.runout_direct = 0
            self.runout_indirect = 0
            self.stumpings = 0
    
            # Played
            self.played = False

            self.points = 0
            self.role = None

        def __str__(self):
            return (
            f"PlayerID: {self.player_id}\n"
            f"Name: {self.name}\n"
            f"Team: {self.team}\n"
            f"Role: {self.role}\n"
            f"Points: {self.points}\n"
            f"Batting:\n"
            f"  Runs: {self.runs}, Balls: {self.balls}, 4s: {self.fours}, 6s: {self.sixes}, SR: {self.strike_rate}\n"
            f"Bowling:\n"
            f"  Overs: {self.overs}, Maidens: {self.maidens}, Runs Conceded: {self.runs_conceded}, "
            f"Wickets: {self.wickets}, Econ: {self.economy}\n"
            f"Fielding:\n"
            f"  Catches: {self.catches}, Runouts (Direct): {self.runout_direct}, "
            f"Runouts (Indirect): {self.runout_indirect}, Stumpings: {self.stumpings}\n"
            f"Dismissal: {self.dismissal}, Is Out: {self.is_out}, Played: {self.played}\n\n"
        )
    
        # =============================
        # DISMISSAL PARSER (PID SAFE)
        # =============================
        def apply_dismissal(self, dismissal_text, match, bowling_team=None):
            self.dismissal = dismissal_text.strip()
    
            if self.dismissal.lower() == "not out":
                self.is_out = False
                return
    
            self.is_out = True
    
            # 🔥 Always resolve via MATCH and bowling team (dismissal is from bowling side)
            def get_player(name):
                if bowling_team:
                    return match.get_player_by_team(name, bowling_team)
                return match.get_player_by_name(name)
    
            # -----------------------
            # CAUGHT
            # -----------------------
            if self.dismissal.startswith("c "):
                match_obj = re.search(r"c\s+(.+?)\s+b\s+(.+)", self.dismissal)
                if match_obj:
                    fielder = get_player(match_obj.group(1))
                    bowler = get_player(match_obj.group(2))
    
                    if fielder:
                        fielder.catches += 1
                    if bowler:
                        bowler.wickets += 1
                return
    
            # -----------------------
            # BOWLED
            # -----------------------
            if self.dismissal.startswith("b "):
                bowler = get_player(self.dismissal.replace("b ", "").strip())
                if bowler:
                    bowler.wickets += 1
                    bowler.bowled += 1
                return
    
            # -----------------------
            # LBW
            # -----------------------
            if self.dismissal.startswith("lbw"):
                match_obj = re.search(r"lbw\s+b\s+(.+)", self.dismissal)
                if match_obj:
                    bowler = get_player(match_obj.group(1))
                    if bowler:
                        bowler.wickets += 1
                        bowler.lbw += 1
                return
    
            # -----------------------
            # STUMPING
            # -----------------------
            if self.dismissal.startswith("st"):
                match_obj = re.search(r"st\s+(.+?)\s+b\s+(.+)", self.dismissal)
                if match_obj:
                    fielder = get_player(match_obj.group(1))
                    bowler = get_player(match_obj.group(2))
    
                    if fielder:
                        fielder.stumpings += 1
                        fielder.runout_direct += 1
                    if bowler:
                        bowler.wickets += 1
                return
    
            # -----------------------
            # RUN OUT
            # -----------------------
            if "run out" in self.dismissal.lower():
                match_obj = re.search(r"\((.*?)\)", self.dismissal)
                if match_obj:
                    fielders = [f.strip() for f in match_obj.group(1).split("/")]
    
                    if len(fielders) == 1:
                        f = get_player(fielders[0])
                        if f:
                            f.runout_direct += 1
                    else:
                        for name in fielders:
                            f = get_player(name)
                            if f:
                                f.runout_indirect += 1
                return
    
    
        # =============================
        # PLAYER POINTS ENGINE
        # =============================
        def calculate_player_points(self, role: str):
            debugPlayerID = 0
            points = 0
            self.role = role
            # -----------------------
            # 🟢 PLAYING
            # -----------------------
            if self.played:
                if self.player_id == debugPlayerID:
                    print("Played points +4")
                points += 4
    
            # -----------------------
            # 🏏 BATTING
            # -----------------------
            runs = self.runs
    
            points += runs
            if self.player_id == debugPlayerID:
                print("Runs points +", str(runs))
    
            # Boundaries
            points += self.fours * 4
            if self.player_id == debugPlayerID:
                print("fours points +", str(self.fours * 4))
            points += self.sixes * 6
            if self.player_id == debugPlayerID:
                print("sixes points +", str(self.sixes * 6))
    
            # Milestones
            if runs >= 100:
                if self.player_id == debugPlayerID:
                    print("+100 runs points +", str(16))
                points += 16
            elif runs >= 50:
                if self.player_id == debugPlayerID:
                    print("+50 runs points +", str(8))
                points += 8
            elif runs >= 30:
                if self.player_id == debugPlayerID:
                    print("+30 runs points +", str(4))
                points += 4
    
            # Duck (only batting roles)
            if runs == 0 and self.is_out and is_batting_role(role):
                if self.player_id == debugPlayerID:
                    print("Duck points -", str(2))
                points -= 2
    
            # Strike Rate (min 10 balls)
            if self.balls >= 10 and is_batting_role(role):
                sr = self.strike_rate
    
                if sr > 170:
                    if self.player_id == debugPlayerID:
                        print("SR+170 points +", str(6))
                    points += 6
                elif sr > 150:
                    if self.player_id == debugPlayerID:
                        print("SR+150 points +", str(4))
                    points += 4
                elif sr >= 130:
                    if self.player_id == debugPlayerID:
                        print("SR+130 points +", str(2))
                    points += 2
                elif sr <= 50:
                    if self.player_id == debugPlayerID:
                        print("SR<50 points -", str(6))
                    points -= 6
                elif sr < 60:
                    if self.player_id == debugPlayerID:
                        print("SR<60 points -", str(4))
                    points -= 4
                elif sr <= 70:
                    if self.player_id == debugPlayerID:
                        print("SR<70 points -", str(2))
                    points -= 2
    
            # -----------------------
            # 🎯 BOWLING
            # -----------------------
            wkts = self.wickets
    
            points += wkts * 30
            if self.player_id == debugPlayerID:
                print("Wickets points +", str(wkts * 30))
    
            # Wicket haul bonus
            if wkts >= 5:
                if self.player_id == debugPlayerID:
                    print("Wickets+5 points +", str(16))
                points += 16
            elif wkts == 4:
                if self.player_id == debugPlayerID:
                    print("Wickets+4 points +", str(8))
                points += 8
            elif wkts == 3:
                if self.player_id == debugPlayerID:
                    print("Wickets+3 points +", str(4))
                points += 4
    
            # Maidens
            points += self.maidens * 12
            if self.player_id == debugPlayerID:
                print("Maidens points +", str(self.maidens * 12))
    
            # Economy (min 2 overs)
            if self.overs >= 2:
                eco = self.economy
    
                if eco < 5:
                    if self.player_id == debugPlayerID:
                        print("Economy<5 points +", str(6))
                    points += 6
                elif eco < 6:
                    if self.player_id == debugPlayerID:
                        print("Economy<6 points +", str(4))
                    points += 4
                elif eco <= 7:
                    if self.player_id == debugPlayerID:
                        print("Economy<7 points +", str(2))
                    points += 2
                elif eco > 12:
                    if self.player_id == debugPlayerID:
                        print("Economy>12 points -", str(6))
                    points -= 6
                elif eco > 11:
                    if self.player_id == debugPlayerID:
                        print("Economy>11 points -", str(4))
                    points -= 4
                elif eco >= 10:
                    if self.player_id == debugPlayerID:
                        print("Economy>10 points -", str(2))
                    points -= 2
    
            # -----------------------
            # 🧤 FIELDING
            # -----------------------
            points += self.catches * 8
            if self.player_id == debugPlayerID:
                print("Catches points +", str(self.catches * 8))
    
            # 3 catch bonus
            if self.catches >= 3:
                if self.player_id == debugPlayerID:
                    print("Catches+3 points +", str(4))
                points += 4
    
            points += self.stumpings * 12
            if self.player_id == debugPlayerID:
                print("Stumpings points +", str(self.stumpings * 12))
            points += self.runout_direct * 12
            if self.player_id == debugPlayerID:
                print("Runout direct points +", str(self.runout_direct * 12))
            points += self.runout_indirect * 6
            if self.player_id == debugPlayerID:
                print("Runout indirect points +", str(self.runout_indirect * 6))

            self.points = points
            if self.player_id == 39:
                print(str(self))
            return points
    
    # =============================
    # PLAYER REGISTRY
    # =============================
    class PlayerRegistry:
        def __init__(self, players_data):
            self.players = {}   # pid → full row
            self.lookup = {}    # (team, normalized name) → pid
    
            self.build(players_data)
    
        def normalize(self, name):
            return " ".join(name.lower().replace(".", "").split())
    
        def build(self, players_data):
            for row in players_data:
                pid = int(row["PlayerID"])
                name = row["Name"]
                team = row["Team"]
    
                self.players[pid] = row
    
                names = [name]
                if row.get("Aliases"):
                    names.extend(row["Aliases"].split(","))
    
                for n in names:
                    normalized = self.normalize(n)
                    self.lookup[(team, normalized)] = pid

                    parts = normalized.split()
                    if len(parts) > 1:
                        self.lookup.setdefault((team, parts[0]), pid)
                        self.lookup.setdefault((team, parts[-1]), pid)
    
        def get_player_id(self, name, team):
            normalized_name = self.normalize(name)
            
            # 1. Try whole name first
            if (team, normalized_name) in self.lookup:
                return self.lookup[(team, normalized_name)]
            
            # 2. Try last name (split by space and take last part)
            name_parts = normalized_name.split()
            if len(name_parts) > 1:
                last_name = name_parts[-1]
                if (team, last_name) in self.lookup:
                    return self.lookup[(team, last_name)]
            
            # 3. Try first name (split by space and take first part)
            if len(name_parts) > 0:
                first_name = name_parts[0]
                if (team, first_name) in self.lookup:
                    return self.lookup[(team, first_name)]
            
            # 4. Not found - print error
            print(f"❌ Player mapping not found: '{name}' (team: {team})")
            return None
    
    # =============================
    # MATCH
    # =============================
    class Match:
        def __init__(self, match_id, team1, team2, registry: PlayerRegistry):
            self.match_id = match_id
            self.team1 = team1
            self.team2 = team2
            self.registry = registry
            self.players = {}  # pid → Player
    
        # -------------------------
        # GET PLAYER ID
        # -------------------------
        def get_player_id(self, name, team):
            return self.registry.get_player_id(clean_name(name), team)
    
        # -------------------------
        # CORE: CREATE BY PID
        # -------------------------
        def get_or_create_player(self, pid):
    
            if not pid:
                return None

            if pid not in self.players:
                
                # ✅ Always fetch full name from registry using PID
                player_data = self.registry.players.get(pid, {})
                full_name = player_data.get("Name", "Unknown")
                print("Creating new player:", str(full_name))

                self.players[pid] = Player(pid, full_name)

            return self.players[pid]
    
        # -------------------------
        # 🔥 USED BY PLAYER CLASS
        # -------------------------
        def get_player_by_name(self, name):
            name = clean_name(name)
    
            pid = self.registry.get_player_id(name, self.team1) \
                  or self.registry.get_player_id(name, self.team2)
    
            if not pid:
                print("❌ Player ID NOT FOUND (dismissal):", name)
                return None
    
            return self.get_or_create_player(pid)
    
        def get_player_by_team(self, name, team):
            name = clean_name(name)
    
            pid = self.registry.get_player_id(name, team)
    
            if not pid:
                print(f"❌ Player ID NOT FOUND in team {team} (dismissal):", name)
                return None
    
            return self.get_or_create_player(pid)
    
        # =============================
        # PARSE SCORECARD
        # =============================
        def parse_scorecard(self, soup: BeautifulSoup):
    
            # ✅ CLEAR OLD PLAYER DATA BEFORE PARSING NEW SCORECARD
            self.players = {}

            def get_table_rows(table):
                rows = []
                for row in table.find_all("tr"):
                    if row.find_parent("table") == table:
                        rows.append(row)
                return rows

            def get_row_cells(row, allowed_tags=("td", "th")):
                cells = []
                for tag in allowed_tags:
                    for cell in row.find_all(tag):
                        if cell.find_parent("tr") == row:
                            cells.append(cell)
                return cells

            def is_int_text(value):
                return bool(re.fullmatch(r"\d+", str(value).strip()))

            def is_float_text(value):
                return bool(re.fullmatch(r"\d+(?:\.\d+)?", str(value).strip()))

            def extract_team_names():
                valid_names = []
                seen = set()

                for tag in soup.find_all(class_="ScorecardCountry3"):
                    text = clean_team_name(tag.get_text(" ", strip=True))
                    if text in TEAM_MAP.values() and text not in seen:
                        seen.add(text)
                        valid_names.append(text)

                return valid_names
    
            team_names = extract_team_names()

            if len(team_names) < 2:
                print("❌ Teams not found")
                return
    
            team1_clean = team_names[0]
            team2_clean = team_names[1]
            print("While parsing scoreboard - " + str(team1_clean) + " vs " + str(team2_clean))
            batting_order = []
    
            # ---------------------------
            # 🟢 BATTING
            # ---------------------------
            batting_tables = []
            seen_tables = set()
            for cell in soup.find_all(["td", "th"]):
                if cell.get_text(" ", strip=True).upper() != "BATTING":
                    continue

                table = cell.find_parent("table")
                if not table:
                    continue

                table_id = id(table)
                if table_id in seen_tables:
                    continue

                seen_tables.add(table_id)
                batting_tables.append(table)
    
            for i, table in enumerate(batting_tables):

                if i >= 2:
                    break
    
                batting_team = team1_clean if i == 0 else team2_clean
                bowling_team = team2_clean if batting_team == team1_clean else team1_clean
                innings_started = False
    
                for r in get_table_rows(table):
                    tds = get_row_cells(r, ("td",))

                    cols = [c.get_text(" ", strip=True) for c in tds]
    
                    # Header/summary rows can appear in the table; ignore non-player rows.
                    if len(cols) < 7:
                        continue

                    first_col_label = cols[0].upper()
                    if first_col_label == "BATTING":
                        if innings_started and batting_team == team1_clean:
                            batting_team = team2_clean
                            bowling_team = team1_clean
                        continue

                    if first_col_label in ("BOWLING", "TOTAL", "EXTRAS", "DNB", "SR", "R"):
                        continue

                    # Batting names are typically links; skip rows without player link.
                    first_td = tds[0] if tds else None
                    if not first_td or not first_td.find("a"):
                        continue

                    # Real batting rows have numeric stat columns for runs/balls/4s/6s.
                    if not all(is_int_text(cols[idx]) for idx in (2, 3, 4, 5)):
                        continue

                    name_link = first_td.find("a")
                    name = clean_name(name_link.get_text(" ", strip=True))
                    pid = self.get_player_id(name, batting_team)

                    if not pid:
                        print(f"❌ Missing ID (bat): {name} | {batting_team}")
                        continue
    
                    player = self.get_or_create_player(pid)
                    innings_started = True

                    if batting_team not in batting_order:
                        batting_order.append(batting_team)
    
                    player.team = batting_team
                    player.played = True
                    player.runs = int(cols[2])
                    player.balls = int(cols[3])
                    player.fours = int(cols[4])
                    player.sixes = int(cols[5])
    
                    if player.balls > 0:
                        # ✅ Round to 2 decimals to avoid floating point precision issues
                        player.strike_rate = round((player.runs / player.balls) * 100, 2)
    
                    # ✅ Pass bowling team into dismissal parser (dismissal is from bowling side)
                    player.apply_dismissal(cols[1], self, bowling_team)

                # Parse "Did Not Bat" within the same batting table so team assignment
                # follows the actual innings context instead of page-wide td order.
                current_batting_team = team1_clean if i == 0 else team2_clean
                innings_seen = False

                for td in table.find_all("td"):
                    td_text = td.get_text(" ", strip=True)

                    if td_text.upper() == "BATTING":
                        if innings_seen and current_batting_team == team1_clean:
                            current_batting_team = team2_clean
                        continue

                    if "Did Not Bat" not in td_text:
                        continue

                    next_td = td.find_next_sibling("td")
                    if not next_td:
                        continue

                    for p in next_td.find_all("a"):
                        name = clean_name(p.get_text(" ", strip=True))
                        pid = self.get_player_id(name, current_batting_team)

                        if not pid:
                            print(f"❌ Missing ID (DNB): {name} | {current_batting_team}")
                            continue

                        player = self.get_or_create_player(pid)
                        player.played = True
                        player.team = current_batting_team

                    innings_seen = True
    
            # ---------------------------
            # 🔵 BOWLING
            # ---------------------------
            bowling_tables = soup.find_all(class_="ScorecardBowling")
    
            for i, table in enumerate(bowling_tables):

                if i >= 2:
                    break
    
                bowling_team = team2_clean if i == 0 else team1_clean
    
                for r in get_table_rows(table)[1:]:
                    tds = get_row_cells(r, ("td",))

                    cols = [c.get_text(" ", strip=True) for c in tds]
    
                    # Ignore non-player/bowling-summary rows
                    if len(cols) < 5:
                        continue

                    first_col_label = cols[0].upper()
                    if first_col_label in ("BOWLING", "TOTAL", "O", "M", "R", "W", "ER", "% WICKETS"):
                        continue

                    # Bowling names are typically links; skip rows without player link.
                    first_td = tds[0] if tds else None
                    if not first_td or not first_td.find("a"):
                        continue

                    # Real bowling rows have numeric overs/maidens/runs/wickets columns.
                    if not is_float_text(cols[1]) or not all(is_int_text(cols[idx]) for idx in (2, 3, 4)):
                        continue

                    name = clean_name(first_td.get_text())
                    pid = self.get_player_id(name, bowling_team)

                    if not pid:
                        print(f"❌ Missing ID (bowl): {name} | {bowling_team}")
                        continue

                    player = self.get_or_create_player(pid)
    
                    player.team = bowling_team
                    player.played = True
                    player.overs = float(cols[1])
                    player.maidens = int(cols[2])
                    player.runs_conceded = int(cols[3])
                    player.wickets = int(cols[4])
    
                    if player.overs > 0:
                        # ✅ Round to 2 decimals to avoid floating point precision issues
                        player.economy = round(player.runs_conceded / player.overs, 2)
    
            print(f"✅ Total players parsed: {len(self.players)}")
            
    # =============================
    # TEAM
    # =============================
    class Team:
        def __init__(self, match_id, player_ids=None, captain=None, vice_captain=None):
            self.match_id = match_id
            self.player_ids = set(player_ids or [])
            self.captain = captain
            self.vice_captain = vice_captain
    
        # 🔥 RENAMED (no collision)
        def calculate_team_points(self, match: Match, player_roles):
            total = 0
    
            for pid in self.player_ids:
                player = match.players.get(pid)
    
                if not player:
                    continue
    
                role = player_roles.get(pid)
    
                if not role:
                    print("❌ Missing role:", player.name)
                    continue
    
                pts = player.calculate_player_points(role)
    
                # Captain / VC multiplier
                if pid == self.captain:
                    pts *= 2
                elif pid == self.vice_captain:
                    pts *= 1.5
    
                total += pts
    
            return total
    
    
    # =============================
    # CONTESTANT
    # =============================
    class Contestant:
        def __init__(self, name, mobile):
            self.name = name
            self.mobile = mobile
            self.teams = {}   # match_id → Team
            self.points = {}  # match_id → points
    
        def add_team(self, team: Team):
            self.teams[team.match_id] = team
    
        # 🔥 RENAMED
        def calculate_points_for_match(self, match: Match, player_roles):
            team = self.teams.get(match.match_id)
    
            if not team:
                return 0
    
            pts = team.calculate_team_points(match, player_roles)
            self.points[match.match_id] = pts
    
            return pts
    
    
    # =============================
    # TOURNAMENT
    # =============================
    class Tournament:
        def __init__(self):
            self.matches = {}       # match_id → Match
            self.contestants = {}  # mobile → Contestant
    
            self.registry = None
            self.player_roles = {}
            self.player_points = {}  # match_id → {pid: points}
    
        # -------------------------
        # INITIALIZE
        # -------------------------
        def initialize(self, players_data, matches_data, teams_data):
    
            # ✅ SINGLE SOURCE
            self.registry = PlayerRegistry(players_data)
    
            # ✅ Role map
            self.player_roles = build_player_role_map(players_data)
    
            # -------------------------
            # CREATE MATCHES
            # -------------------------
            for m in matches_data:
                match_id = str(m["MatchID"])
    
                self.matches[match_id] = Match(
                    match_id,
                    m["Team1"],
                    m["Team2"],
                    self.registry
                )
    
            # -------------------------
            # CREATE CONTESTANTS + TEAMS
            # -------------------------
            for row in teams_data:
                mobile = str(row["Mobile"])
                match_id = str(row["MatchID"])
                pid = int(row["PlayerID"])
    
                if mobile not in self.contestants:
                    self.contestants[mobile] = Contestant(
                        row["User"],
                        mobile
                    )
    
                contestant = self.contestants[mobile]
    
                if match_id not in contestant.teams:
                    contestant.teams[match_id] = Team(match_id)
    
                team = contestant.teams[match_id]
                team.player_ids.add(pid)
    
                if str(row["Captain"]).lower() == "true":
                    team.captain = pid
    
                if str(row["ViceCaptain"]).lower() == "true":
                    team.vice_captain = pid
    

        # -------------------------
        # UPDATE MATCH DATA
        # -------------------------
        def update_match_data(self, match_id):
    
            match = self.matches.get(match_id)
    
            if not match:
                return
    
            print(f"\n📊 Updating Match {match_id}")
    
            match_code = int(match_id) + MATCH_CODE_OFFSET
            html_text = fetch_scorecard_html(match_code)
    
            if not html_text:
                print("❌ No scorecard")
                return
    
            soup = BeautifulSoup(html_text, "html.parser")
    
            match.parse_scorecard(soup)
    
            # Debug
            #for p in match.players.values():
                #print(p.name, p.runs, p.wickets, p.catches)
    
        # -------------------------
        # DETERMINE MATCH STATUS
        # -------------------------
        def get_match_status(self, match):
            """
            Returns: 'future', 'live', 'over'
            """
            try:
                match_datetime = datetime.strptime(
                    f"{match['Date']} {match['Time']}",
                    "%Y-%m-%d %H:%M"
                )
                match_datetime = ist.localize(match_datetime)
            except:
                return None
    
            if TEST_MODE:
                now = ist.localize(datetime(
                    2025,
                    TEST_MODE_MONTH,
                    TEST_MODE_DATE,
                    TEST_MODE_TIME_HR,
                    TEST_MODE_TIME_MIN
                ))
            else:
                now = datetime.now(ist)
    
            if now < match_datetime:
                return 'future'
            elif now >= match_datetime and now < match_datetime + timedelta(hours=5):
                return 'live'
            else:
                return 'over'
    
        # -------------------------
        # GET ALREADY COMPUTED POINTS
        # -------------------------
        def get_computed_points(self):
            """
            Returns dict: {(mobile, match_id): points}
            """
            computed = {}
            try:
                sheet = client.open("FantasyCricket").worksheet("ContestantPoints")
                records = sheet.get_all_records()
                for row in records:
                    mobile = str(row["Mobile"])
                    match_id = str(row["MatchID"])
                    points = float(row["Points"])
                    computed[(mobile, match_id)] = points
            except:
                pass
            return computed
    
        # -------------------------
        # GET ALREADY COMPUTED PLAYER POINTS
        # -------------------------
        def get_computed_player_points(self):
            """
            Returns dict: {(match_id, pid): points}
            """
            computed = {}
            try:
                sheet = client.open("FantasyCricket").worksheet("PlayerPoints")
                records = sheet.get_all_records()
                for row in records:
                    match_id = str(row["MatchID"])
                    pid = int(row["PlayerID"])
                    points = float(row["Points"])
                    computed[(match_id, pid)] = points
            except:
                pass
            return computed
    
        # -------------------------
        # COMPUTE PLAYER POINTS FOR MATCH
        # -------------------------
        def compute_player_points_for_match(self, match_id):
            """
            Calculate points for each player in a match
            """
            match = self.matches.get(match_id)
            if not match:
                return
    
            player_points = {}
    
            for pid, player in match.players.items():
                role = self.player_roles.get(pid)
                if not role:
                    continue
    
                points = player.calculate_player_points(role)
                player_points[pid] = points
    
            self.player_points[match_id] = player_points
    
        # -------------------------
        # COMPUTE POINTS FOR MATCH
        # -------------------------
        def compute_points_for_match(self, match_id):
            """
            Compute points for a specific match for all contestants
            """
            for contestant in self.contestants.values():
                match = self.matches.get(match_id)
                if match:
                    contestant.calculate_points_for_match(
                        match,
                        self.player_roles
                    )
    
        # -------------------------
        # SCHEDULER
        # -------------------------
        def start_scheduler(self):
    
            def run():
                while True:
                    try:
                        print("\n🔄 Scheduler running...")
    
                        matches_data = get_cached_data("matches")
                        computed_points = self.get_computed_points()
    
                        for m in matches_data:
                            match_id = str(m["MatchID"])
                            status = self.get_match_status(m)
    
                            # =============================
                            # FUTURE MATCHES
                            # =============================
                            if status == 'future':
                                continue
    
                            # =============================
                            # LIVE MATCHES
                            # =============================
                            if status == 'live':
                                print(f"Match {match_id} 🔴 LIVE - Fetching latest data")
                                self.update_match_data(match_id)
                                self.compute_player_points_for_match(match_id)
                                self.compute_points_for_match(match_id)
                                continue
    
                            # =============================
                            # COMPLETED MATCHES
                            # =============================
                            if status == 'over':
                                # Check if already computed
                                already_computed = False
                                for contestant in self.contestants.values():
                                    key = (contestant.mobile, match_id)
                                    if key in computed_points:
                                        already_computed = True
                                        break
    
                                if already_computed:
                                    print(f"    ✅ Already computed (skipping)")
                                    # Load existing points
                                    for contestant in self.contestants.values():
                                        key = (contestant.mobile, match_id)
                                        if key in computed_points:
                                            contestant.points[match_id] = computed_points[key]
                                else:
                                    print(f"    🔵 FINISHED - Computing points for first time")
                                    self.update_match_data(match_id)
                                    self.compute_player_points_for_match(match_id)
                                    self.compute_points_for_match(match_id)
    
                        # =============================
                        # PERSIST TO SHEETS (EVERY LOOP)
                        # =============================
                        print("\n💾 Persisting to sheets...")
                        self.persist_to_sheets()
                        self.persist_player_points_to_sheets()
    
                    except Exception as e:
                        print(f"❌ Scheduler error: {e}")
                        import traceback
                        traceback.print_exc()
    
                    time.sleep(60)
    
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
    
        # -------------------------
        # SAVE TO GOOGLE SHEETS
        # -------------------------
        def persist_to_sheets(self):
    
            print("💾 Persisting all contestant points...")
    
            rows = []
    
            now_str = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")
    
            for contestant in self.contestants.values():
                for match_id, pts in contestant.points.items():
    
                    rows.append([
                        contestant.name,
                        contestant.mobile,
                        match_id,
                        round(pts, 2),
                        now_str
                    ])
    
            if not rows:
                print("⚠️  No data to persist")
                return
    
            try:
                sheet = client.open("FantasyCricket").worksheet("ContestantPoints")
            except:
                sheet = client.open("FantasyCricket").add_worksheet(
                    title="ContestantPoints",
                    rows="1000",
                    cols="10"
                )
    
            # Header
            all_values = sheet.get_all_values()
            if not all_values:
                sheet.append_row([
                    "User",
                    "Mobile",
                    "MatchID",
                    "Points",
                    "LastUpdated"
                ])
    
            # Clear old data - delete all rows except header (row 1)
            if len(all_values) > 1:
                sheet.delete_rows(2, len(all_values))
    
            # Write new data - append all new rows
            if rows:
                sheet.append_rows(rows)
    
            print(f"✅ Persisted {len(rows)} rows")
    
        # -------------------------
        # SAVE PLAYER POINTS TO GOOGLE SHEETS
        # -------------------------
        def persist_player_points_to_sheets(self):
    
            print("💾 Persisting player points...")
    
            rows = []
    
            now_str = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")
    
            # Iterate through each match and its player points
            for match_id, player_points in self.player_points.items():
                match = self.matches.get(match_id)
                if not match:
                    continue
    
                for pid, points in player_points.items():
                    player = match.players.get(pid)
                    player_info = self.registry.players.get(pid)
    
                    if not player_info:
                        continue
    
                    rows.append([
                        match_id,
                        pid,
                        player.name,
                        player_info.get("Team", ""),
                        player_info.get("Role", ""),
                        round(points, 2),
                        now_str
                    ])
    
            if not rows:
                print("⚠️  No player points to persist")
                return
    
            try:
                sheet = client.open("FantasyCricket").worksheet("PlayerPoints")
            except:
                sheet = client.open("FantasyCricket").add_worksheet(
                    title="PlayerPoints",
                    rows="5000",
                    cols="10"
                )
    
            # Header
            all_values = sheet.get_all_values()
            if not all_values:
                sheet.append_row([
                    "MatchID",
                    "PlayerID",
                    "PlayerName",
                    "Team",
                    "Role",
                    "Points",
                    "LastUpdated"
                ])
    
            # Clear old data - delete all rows except header (row 1)
            if len(all_values) > 1:
                sheet.delete_rows(2, len(all_values))
    
            # Write new data - append all new rows
            if rows:
                sheet.append_rows(rows)
    
            print(f"✅ Persisted {len(rows)} player points")
    
    # 🔐 Check if match locked
    #def is_match_locked(match_datetime_str):
    #    match_time = datetime.strptime(match_datetime_str, "%Y-%m-%d %H:%M")
    #    match_time = ist.localize(match_time)
    #    if TEST_MODE:
    #        now = ist.localize(datetime(2025, TEST_MODE_MONTH, TEST_MODE_DATE, TEST_MODE_TIME_HR, TEST_MODE_TIME_MIN))
    #    else:
    #        now = datetime.now(ist)
    #    return now >= match_time
    
    # 🏠 LOGIN PAGE
    @app.get("/", response_class=HTMLResponse)
    def login_page(request: Request):
        error = request.query_params.get("error", "")
    
        msg = ""
        if error == "invalid":
            msg = "<div class='message error'>Invalid credentials</div>"

        mobile_body = f"""
        <div class="panel-card" style="max-width:480px; margin:0 auto;">
            <div class="kicker">Fantasy Cricket</div>
            <h1 style="margin-top:6px;">Hippies Mahasangram</h1>
            <p class="muted">Sign in to select your team, track scores, and follow the leaderboard comfortably on mobile.</p>
            {msg}
            <form action="/login" method="post" class="form-grid">
                <div>
                    <label for="mobile">Mobile Number</label>
                    <input id="mobile" type="text" name="mobile" inputmode="numeric" autocomplete="tel" placeholder="Enter your mobile number" required>
                </div>
                <div>
                    <label for="password">Password</label>
                    <input id="password" type="password" name="password" autocomplete="current-password" placeholder="Enter your password" required>
                </div>
                <div class="button-row">
                    <button class="btn btn-primary" type="submit">Login</button>
                </div>
            </form>
        </div>
        """

        return render_page("Login", mobile_body)
        """
    
        
        <h1>🏏 Hippies Mahasangram Login</h1>
        
        <form action="/login" method="post">
            Mobile Number: <input type="text" name="mobile" required><br><br>
            Password: <input type="password" name="password" required><br><br>
            <button type="submit">Login</button>
        </form>
        """
    
    # 🔐 LOGIN API
    @app.post("/login")
    def login(request: Request, mobile: str = Form(...), password: str = Form(...)):
        users = get_cached_data("users")
    
        mobile = str(mobile).strip()
        password = str(password).strip()
    
        for u in users:
            sheet_mobile = str(u["Mobile"]).strip()
            sheet_password = str(u.get("Password", "")).strip()
            allowed = str(u["Allowed"]).strip().lower()
    
            if sheet_mobile == mobile and sheet_password == password and allowed == "true":
                request.session['mobile'] = mobile
                request.session['name'] = u["Name"]
    
                return RedirectResponse(url="/dashboard", status_code=303)
    
        return RedirectResponse(url="/?error=invalid", status_code=303)
        
    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        mobile = request.session.get('mobile')
        if not mobile:
            return RedirectResponse(url="/", status_code=302)
    
        name = request.session.get('name')
        matches = get_cached_data("matches")

        msg_param = request.query_params.get("msg", "")
        flash = ""
        if msg_param == "passchanged":
            flash = "<div class='message success'>Password updated successfully.</div>"
        elif msg_param == "teamsaved":
            flash = "<div class='message success'>Your team has been saved.</div>"

        body = f"""
        <h2>Welcome {name}</h2>
        <p class="muted">Pick your team before match lock and keep an eye on live standings.</p>
        {flash}
        <div class="actions-grid">
            <a href="/change-password" class="btn btn-danger">Change Password</a>
            <a href="/leaderboard" class="btn btn-warning">Leaderboard</a>
            <a href="/points-table" class="btn btn-primary">Points Table</a>
            <a href="/logout" class="btn btn-secondary">Logout</a>
        </div>
        <div class="match-list">
        """

        for m in matches:
            locked = is_match_locked_by_row(m)

            if locked:
                action_button = f'<a href="/view-scores?match_id={m["MatchID"]}" class="btn btn-success">View Scores</a>'
            else:
                action_button = f'<a href="/select-team?match_id={m["MatchID"]}" class="btn btn-primary">Select Team</a>'

            body += f"""
            <div class="match-card">
                <div class="match-meta">
                    <div class="kicker">Match {m['MatchID']}</div>
                    <div><b>{m['Team1']} vs {m['Team2']}</b></div>
                    <div class="muted">{m['Date']} at {m['Time']}</div>
                </div>
                <div>{action_button}</div>
            </div>
            """

        body += "</div>"

        return render_page("Dashboard", body)
    
        legacy_html = f"""
        <h2>Welcome {name}</h2>
    
        <a href="/change-password"
           style="padding:8px 14px; background:#dc3545; color:white; text-decoration:none; border-radius:6px;">
           🔑 Change Password
        </a>
        <br><br>
    
        <a href="/leaderboard"
           style="padding:8px 14px; background:#ff9800; color:white; text-decoration:none; border-radius:6px;">
           🏆 Leaderboard
        </a>
        <br><br>
    
        <a href="/points-table"
           style="padding:8px 14px; background:#6f42c1; color:white; text-decoration:none; border-radius:6px;">
           📊 Points Table
        </a>
        <br><br>
    
        <a href="/logout"
           style="padding:8px 14px; background:#6c757d; color:white; text-decoration:none; border-radius:6px;">
           🚪 Logout
        </a>
        <br><br>
        """
    
        for m in matches:
            locked = is_match_locked_by_row(m)
    
            if locked:
                action_button = f"""
                <a href="/view-scores?match_id={m['MatchID']}"
                   style="padding:6px 12px; background:#28a745; color:white; text-decoration:none; border-radius:5px;">
                   View Scores
                </a>
                """
            else:
                action_button = f"""
                <a href="/select-team?match_id={m['MatchID']}"
                   style="padding:6px 12px; background:#007bff; color:white; text-decoration:none; border-radius:5px;">
                   Select Team
                </a>
                """
    
            html += f"""
            <div style="display:flex; align-items:center; gap:20px; margin-bottom:12px;">
                <div><b>Match {m['MatchID']}</b></div>
                <div>{m['Team1']} vs {m['Team2']}</div>
                <div>{action_button}</div>
            </div>
            """
    
        return render_page("Select Team", html)
    
    # 🚪 LOGOUT
    @app.get("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse(url="/", status_code=302)
    
    # 🔑 CHANGE PASSWORD PAGE
    @app.get("/change-password", response_class=HTMLResponse)
    def change_password_page(request: Request):
        mobile = request.session.get('mobile')
        if not mobile:
            return RedirectResponse(url="/", status_code=302)

        error = request.query_params.get("error", "")
        msg = ""
        if error == "nomatch":
            msg = "<div class='message error'>New password and confirmation do not match.</div>"
        elif error == "wrongpass":
            msg = "<div class='message error'>Current password is incorrect.</div>"
        elif error == "server":
            msg = "<div class='message error'>Could not update the password right now. Please try again.</div>"

        body = f"""
        <h1>Change Password</h1>
        <p class="muted">Use a password you can remember easily on mobile.</p>
        {msg}
        <form action="/change-password" method="post" class="form-grid">
            <div>
                <label for="current_password">Current Password</label>
                <input id="current_password" type="password" name="current_password" required>
            </div>
            <div>
                <label for="new_password">New Password</label>
                <input id="new_password" type="password" name="new_password" required>
            </div>
            <div>
                <label for="confirm_password">Confirm New Password</label>
                <input id="confirm_password" type="password" name="confirm_password" required>
            </div>
            <div class="button-row">
                <button class="btn btn-primary" type="submit">Change Password</button>
            </div>
        </form>
        <a class="back-link" href='/dashboard'>Back to dashboard</a>
        """

        return render_page("Change Password", body)
        
        return f"""
        <h1>🔑 Change Password</h1>
        <form action="/change-password" method="post">
            Current Password: <input type="password" name="current_password" required><br><br>
            New Password: <input type="password" name="new_password" required><br><br>
            Confirm New Password: <input type="password" name="confirm_password" required><br><br>
            <button type="submit">Change Password</button>
        </form>
        <br><a href='/dashboard'>⬅ Back</a>
        """
    
    # 🔑 CHANGE PASSWORD API
    @app.post("/change-password")
    def change_password(
        request: Request,
        current_password: str = Form(...),
        new_password: str = Form(...),
        confirm_password: str = Form(...)
    ):
        mobile = request.session.get('mobile')
        if not mobile:
            return RedirectResponse(url="/", status_code=302)
    
        if new_password != confirm_password:
            return RedirectResponse(url="/change-password?error=nomatch", status_code=303)
    
        users = get_cached_data("users")
    
        user_row = None
        row_index = 0
    
        for idx, u in enumerate(users, start=2):
            if str(u["Mobile"]).strip() == mobile:
                user_row = u
                row_index = idx
                break
    
        if not user_row or str(user_row.get("Password", "")).strip() != current_password:
            return RedirectResponse(url="/change-password?error=wrongpass", status_code=303)
    
        try:
            sheet = client.open("FantasyCricket").worksheet("Users")
            sheet.update_cell(row_index, 4, new_password)
    
            return RedirectResponse(url="/dashboard?msg=passchanged", status_code=303)
    
        except Exception:
            return RedirectResponse(url="/change-password?error=server", status_code=303)
            
    
    # 🧾 TEAM SELECTION PAGE
    @app.get("/select-team", response_class=HTMLResponse)
    def select_team(request: Request, match_id: str):
        mobile = request.session.get('mobile')
        if not mobile:
            return RedirectResponse(url="/", status_code=302)
        
        from datetime import datetime
        import pytz
    
        matches = get_cached_data("matches")
        match = next((m for m in matches if int(m["MatchID"]) == int(match_id)), None)
    
        if not match:
            return "<h3>❌ Match not found</h3>"
    
        team1 = match["Team1"]
        team2 = match["Team2"]
    
        try:
            match_datetime = datetime.strptime(
                f"{match['Date']} {match['Time']}",
                "%Y-%m-%d %H:%M"
            )
            match_datetime = ist.localize(match_datetime)
        except Exception as e:
            return f"<h3>❌ Invalid match time format: {e}</h3>"
    
        if TEST_MODE:
            now = ist.localize(datetime(2025, TEST_MODE_MONTH, TEST_MODE_DATE, TEST_MODE_TIME_HR, TEST_MODE_TIME_MIN))
        else:
            now = datetime.now(ist)
    
        if now >= match_datetime:
            return "<h3>⛔ Match locked</h3>"
    
        # 🏏 Filter players
        players = [
            p for p in get_cached_data("players")
            if p["Team"] in [team1, team2]
        ]
        
        seen = set()
        unique_players = []
        
        for p in players:
            key = (p["Name"], p["Team"])
            if key not in seen:
                seen.add(key)
                unique_players.append(p)
    
        players = unique_players
        player_total_points = get_player_total_points()

        for p in players:
            p["TotalPoints"] = player_total_points.get(str(p["PlayerID"]).strip(), 0)
    
        grouped = {role: [] for role in ROLES}
    
        for p in players:
            if p["Role"] in grouped:
                grouped[p["Role"]].append(p)

        for role_players in grouped.values():
            role_players.sort(
                key=lambda player: (-player.get("TotalPoints", 0), player["Name"])
            )

        html = f"""
        <h2>{team1} vs {team2}</h2>
        <p class="selection-summary">Select exactly 11 players with at least one from each category.</p>

        <form method="post" action="/submit-team" onsubmit="return validateForm()">
        <input type="hidden" name="match_id" value="{match_id}">
        """

        def render_section_mobile(title, plist):
            section = f"<section class='team-section'><h3>{title}</h3><div class='table-scroll'><table>"
            section += """
                <tr>
                    <th>Select</th>
                    <th>C</th>
                    <th>VC</th>
                    <th>Player</th>
                    <th>Total Points</th>
                </tr>
            """

            for p in plist:
                section += f"""
                <tr>
                    <td>
                        <input type="checkbox"
                         class="player-checkbox"
                         data-role="{p['Role']}"
                         name="players"
                         value="{p['PlayerID']}"
                         onchange="toggleRadio(this); limitSelection()">
                    </td>
                    <td>
                        <input type="radio" name="captain" value="{p['PlayerID']}" id="mc{p['PlayerID']}" disabled>
                    </td>
                    <td>
                        <input type="radio" name="vice_captain" value="{p['PlayerID']}" id="mvc{p['PlayerID']}" disabled>
                    </td>
                    <td>{p['Name']} ({p['Team']})</td>
                    <td>{p.get('TotalPoints', 0):.2f}</td>
                </tr>
                """

            section += "</table></div></section>"
            return section

        html += render_section_mobile("Wicketkeepers", grouped["Wicketkeeper"])
        html += render_section_mobile("Batter", grouped["Batter"])
        html += render_section_mobile("AllRounder", grouped["AllRounder"])
        html += render_section_mobile("Bowlers", grouped["Bowler"])
    
        
    
        # 🧠 JAVASCRIPT LOGIC
        html += f"""
    <script>
    const ROLES = {ROLES};
    """
    
        html +="""
    function validateForm() {
        let selected = document.querySelectorAll(".player-checkbox:checked");
    
        if (selected.length !== 11) {
            alert("Select exactly 11 players");
            return false;
        }
    
        let captain = document.querySelector("input[name='captain']:checked");
        let vc = document.querySelector("input[name='vice_captain']:checked");
    
        if (!captain) {
            alert("Please select a Captain");
            return false;
        }
    
        if (!vc) {
            alert("Please select a Vice Captain");
            return false;
        }
    
        if (captain.value === vc.value) {
            alert("Captain and Vice Captain cannot be same");
            return false;
        }
        
        // Disable buttons during submission
        document.querySelector('button[type="submit"]').disabled = true;
        document.querySelector('button[type="button"]').disabled = true;
        document.querySelector('button[type="submit"]').textContent = 'Submitting...';
    
        return true;
    }
    function toggleRadio(checkbox) {
        let row = checkbox.closest("tr");
    
        let cap = row.querySelector("input[name='captain']");
        let vc = row.querySelector("input[name='vice_captain']");
    
        if (checkbox.checked) {
            cap.disabled = false;
            vc.disabled = false;
        } else {
            cap.checked = false;
            vc.checked = false;
            cap.disabled = true;
            vc.disabled = true;
        }
    }
    function limitSelection() {
        let checkboxes = document.querySelectorAll(".player-checkbox");
        let checked = document.querySelectorAll(".player-checkbox:checked");
    
        let total = checked.length;
    
        // 🔴 STEP 1: HARD LIMIT (FIRST)
        if (total > 11) {
            alert("You can select only 11 players");
    
            let last = checked[checked.length - 1];
            last.checked = false;
    
            return limitSelection();
        }
    
        let roleCount = {};
        ROLES.forEach(role => roleCount[role] = 0);
    
        // Count roles safely
        checked.forEach(cb => {
            let role = cb.getAttribute("data-role");
            if (roleCount.hasOwnProperty(role)) {
                roleCount[role]++;
            }
        });
    
        let remaining = 11 - total;
        let missingRoles = [];
    
        ROLES.forEach(role => {
            if (!roleCount[role]) {
                missingRoles.push(role);
            }
        });
    
        // 🔒 STEP 2: Prevent invalid final combination
        if (total === 11 && missingRoles.length > 0) {
            alert("You must select at least 1 player from each category");
    
            let last = checked[checked.length - 1];
            last.checked = false;
    
            return limitSelection();
        }
    
        // 🔒 STEP 3: Smart restriction
        if (remaining === missingRoles.length) {
            checkboxes.forEach(cb => {
                let role = cb.getAttribute("data-role");
    
                if (!cb.checked && !missingRoles.includes(role)) {
                    cb.disabled = true;
                } else {
                    cb.disabled = false;
                }
            });
            return;
        }
    
        // 🔒 STEP 4: Lock at 11
        if (total === 11) {
            checkboxes.forEach(cb => {
                if (!cb.checked) cb.disabled = true;
            });
            return;
        }
    
        // 🔓 STEP 5: Default
        checkboxes.forEach(cb => {
            cb.disabled = false;
        });
    }
    
    // Prevent same Captain & VC
    document.addEventListener("change", function(e) {
        if (e.target.name === "captain" || e.target.name === "vice_captain") {
            let captain = document.querySelector("input[name='captain']:checked");
            let vc = document.querySelector("input[name='vice_captain']:checked");
    
            if (captain && vc && captain.value === vc.value) {
                alert("Captain and Vice Captain cannot be same");
                e.target.checked = false;
            }
        }
    });
    </script>
        """
    
        html += """
        <br>
        <button type="submit">Submit Team</button>
        <button type="button" onclick="window.history.back()">⬅ Back</button>
        </form>
        """
    
        return render_page("Select Team", html)
    
    
    
    @app.post("/submit-team")
    def submit_team(
        request: Request,
        match_id: str = Form(...),
        players: list[str] = Form(...),
        captain: Optional[str] = Form(None),
        vice_captain: Optional[str] = Form(None)
    ):
        mobile = request.session.get('mobile')
        if not mobile:
            return RedirectResponse(url="/", status_code=302)
    
        users = get_cached_data("users")
        user = next((u for u in users if str(u["Mobile"]) == str(mobile)), None)
    
        if not user:
            return "<h3>❌ User not found</h3>"
    
        name = user["Name"]
        
        # 🟢 STEP 1: CHECK MATCH LOCK
        matches = get_cached_data("matches")
        match = next((m for m in matches if int(m["MatchID"]) == int(match_id)), None)
    
        if not match:
            return "<h3>❌ Match not found</h3>"
    
        match_time = datetime.strptime(
            f"{match['Date']} {match['Time']}",
            "%Y-%m-%d %H:%M"
        )
        if TEST_MODE:
            now = ist.localize(datetime(2025, TEST_MODE_MONTH, TEST_MODE_DATE, TEST_MODE_TIME_HR, TEST_MODE_TIME_MIN))
        else:
            now = datetime.now(ist)
    
        if now > ist.localize(match_time):
            return "<h3>⛔ Team submission closed (match started)</h3>"
    
        # 🟢 STEP 2: VALIDATION RULES
        players_data = get_cached_data("players")
        selected_ids = [int(p) for p in players]
    
        # ❌ Rule 1: Exactly 11 players
        if len(selected_ids) != 11:
            return "<h3>❌ Select exactly 11 players</h3>"
            
        if captain == vice_captain:
            return "<h3>❌ Captain and Vice Captain cannot be same</h3>"
    
        selected_players = [p for p in players_data if int(p["PlayerID"]) in selected_ids]
    
        # Role count
        roles = {role: 0 for role in ROLES}
    
        for p in selected_players:
            role = p["Role"]
            if role in roles:
                roles[role] += 1
    
        # ❌ Role validations
        if roles["Batter"] < 1:
            return "<h3>❌ At least 1 Batter required</h3>"
    
        if roles["Bowler"] < 1:
            return "<h3>❌ At least 1 Bowler required</h3>"
    
        if roles["AllRounder"] < 1:
            return "<h3>❌ At least 1 AllRounder required</h3>"
    
        if roles["Wicketkeeper"] < 1:
            return "<h3>❌ At least 1 Wicketkeeper required</h3>"
            
        if not captain:
            return "<h3>❌ Captain not selected</h3>"
    
        if not vice_captain:
            return "<h3>❌ Vice Captain not selected</h3>"
    
        # ❌ Captain validation
        if int(captain) not in selected_ids:
            return "<h3>❌ Captain must be selected</h3>"
    
        if int(vice_captain) not in selected_ids:
            return "<h3>❌ Vice Captain must be selected</h3>"
    
        if captain == vice_captain:
            return "<h3>❌ Captain and Vice Captain cannot be same</h3>"
            
        # 🟢 REMOVE OLD TEAM (IF EXISTS)
        all_rows = teams_sheet.get_all_records()
    
        rows_to_delete = []
    
        for idx, row in enumerate(all_rows, start=2):  # row 1 = header
            if str(row["Mobile"]) == str(mobile) and int(row["MatchID"]) == int(match_id):
                rows_to_delete.append(idx)
    
        # ⚠️ Delete from bottom to top
        for r in reversed(rows_to_delete):
            teams_sheet.delete_rows(r)
    
        # 🟢 STEP 4: SAVE NEW TEAM
        for pid in selected_ids:
            player = next((p for p in selected_players if int(p["PlayerID"]) == int(pid)), None)
            player_name = player["Name"] if player else ""
            teams_sheet.append_row([
                name,
                mobile,
                match_id,
                pid,
                player_name,
                "TRUE" if str(pid) == captain else "FALSE",
                "TRUE" if str(pid) == vice_captain else "FALSE"
            ])
    
        return RedirectResponse(url="/dashboard?msg=teamsaved", status_code=303)
    
    # 👁️ VIEW TEAMS (AFTER LOCK)
    @app.get("/view-teams", response_class=HTMLResponse)
    def view_teams(match_id: str):
    
        matches = matches_sheet.get_all_records()
        match = next((m for m in matches if int(m["MatchID"]) == int(match_id)), None)
        
        if not match:
            return "<h3>❌ Match not found</h3>"
    
        if not is_match_locked(match["DateTime"]):
            return "<h3>🔒 Teams will be visible after match starts</h3>"
    
        teams = teams_sheet.get_all_records()

        body = "<h2>All Teams</h2><div class='match-list'>"

        for t in teams:
            if int(t["MatchID"]) == int(match_id):
                body += f"<div class='match-card'><div><b>{t['User']}</b></div><div>Player {t['PlayerID']}</div></div>"

        body += "</div>"

        return render_page("All Teams", body)
    
    tournament = Tournament()
        
    @app.get("/view-scores", response_class=HTMLResponse)
    def view_scores(match_id: str):

        body = f"""
        <h2>Match {match_id} Live Score</h2>
        <p class="compact-note">Swipe inside the tables on smaller screens to see every stat without the page feeling loose.</p>
        <div id="loader" class="message success" style="display:none;"></div>
        <div class="score-layout">
            <div id="players-container" class="panel-card">
                <h3>Player Statistics</h3>
                <div id="players-table" class="table-scroll"></div>
            </div>
            <div id="contestants-container" class="panel-card">
                <h3>Contestant Rankings</h3>
                <div id="contestants-table" class="table-scroll"></div>
            </div>
        </div>
        <a class="back-link" href='/dashboard'>Back to dashboard</a>
        <script>
        let firstLoad = true;
        let userTeam = [];

        async function loadScores() {{
            const loader = document.getElementById('loader');

            if (firstLoad) {{
                loader.textContent = 'Loading scores...';
                loader.style.display = 'block';
            }} else {{
                loader.textContent = 'Refreshing live scores...';
                loader.style.display = 'block';
            }}

            try {{
                if (firstLoad) {{
                    let teamRes = await fetch('/user-team-data?match_id={match_id}');
                    userTeam = await teamRes.json();
                }}

                let res = await fetch('/match-score-data?match_id={match_id}');
                let data = await res.json();

                if (data.error) {{
                    document.getElementById("players-table").innerHTML = '<p>' + data.error + '</p>';
                    document.getElementById("contestants-table").innerHTML = '<p>' + data.error + '</p>';
                    loader.style.display = 'none';
                    return;
                }}

                let playersHTML = `
                                  <table>
                                  <thead>
                                  <tr>
                                  <th>Name</th>
                                  <th style="font-weight: bold; color: #2e7d32;">Points</th>
                                  <th>Team</th>
                                  <th>Role</th>
                                  <th>Runs</th>
                                  <th>Balls</th>
                                  <th>4s</th>
                                  <th>6s</th>
                                  <th>SR</th>
                                  <th>Overs</th>
                                  <th>Maidens</th>
                                  <th>Wkts</th>
                                  <th>B/LBW</th>
                                  <th>Eco</th>
                                  <th>Catches</th>
                                  <th>RO+St</th>
                                  <th>RO Ind</th>
                                  </tr>
                                  </thead>
                                  <tbody>`;
                data.players.forEach(p => {{
                    let rowClass = userTeam.includes(p.name) ? 'user-team' : '';
                    playersHTML += `<tr class="${{rowClass}}">
                                    <td>${{p.name}}</td>
                                    <td style="font-weight: bold;">${{p.points.toFixed(2)}}</td>
                                    <td>${{p.team}}</td>
                                    <td>${{p.role}}</td>
                                    <td>${{p.runs || 0}}</td>
                                    <td>${{p.balls || 0}}</td>
                                    <td>${{p.fours || 0}}</td>
                                    <td>${{p.sixes || 0}}</td>
                                    <td>${{p.strike_rate || 0}}</td>
                                    <td>${{p.overs || 0}}</td>
                                    <td>${{p.maidens || 0}}</td>
                                    <td>${{p.wickets || 0}}</td>
                                    <td>${{(p.bowled || 0) + (p.lbw || 0)}}</td>
                                    <td>${{p.economy || 0}}</td>
                                    <td>${{p.catches || 0}}</td>
                                    <td>${{(p.runout_direct || 0) + (p.stumpings || 0)}}</td>
                                    <td>${{p.runout_indirect || 0}}</td>
                                    </tr>`;
                }});
                playersHTML += '</tbody></table>';
                document.getElementById("players-table").innerHTML = playersHTML;

                let contestantsHTML = '<table><thead><tr><th>Contestant</th><th>Points</th></tr></thead><tbody>';
                data.contestants.forEach(c => {{
                    contestantsHTML += `<tr><td>${{c.name}}</td><td>${{c.points.toFixed(2)}}</td></tr>`;
                }});
                contestantsHTML += '</tbody></table>';
                document.getElementById("contestants-table").innerHTML = contestantsHTML;

                loader.style.display = 'none';

                if (firstLoad) {{
                    firstLoad = false;
                }}

            }} catch (e) {{
                console.log("Error loading scores", e);
                loader.textContent = 'Error loading scores. Please try again.';
                if (firstLoad) {{
                    firstLoad = false;
                }}
            }}
        }}

        loadScores();
        setInterval(loadScores, 30000);
        </script>
        """

        return render_page("Live Scores", body)
    
        html = f"""
        <h2>Match {match_id} - Live Score</h2>
    
        <div id="loader" style="display:none; margin-bottom:10px;"></div>
        <div style="display:flex; gap:20px;">
            <div id="players-container">
                <h3>Player Statistics</h3>
                <div id="players-table" style="overflow-x:auto;"></div>
            </div>
            <div id="contestants-container">
                <h3>Contestant Rankings</h3>
                <div id="contestants-table" style="overflow-x:auto;"></div>
            </div>
        </div>
    
        <br><a href='/dashboard'>⬅ Back</a>
    
        <style>
            #players-table, #contestants-table {{
                border-collapse: collapse;
                width: 100%;
                min-width: 400px;
            }}
            #players-table th, #players-table td, #contestants-table th, #contestants-table td {{
                border: 1px solid #ccc;
                padding: 8px;
                text-align: left;
            }}
            #players-table th, #contestants-table th {{
                background: #f4f4f8;
            }}
            #players-table tr:nth-child(even), #contestants-table tr:nth-child(even) {{
                background: #fafafa;
            }}
            .user-team {{
                background: #fff3cd;
                font-weight: bold;
            }}
        </style>
    
        <script>
        let firstLoad = true;
        let userTeam = [];

        async function loadScores() {{
            const loader = document.getElementById('loader');

            if (firstLoad) {{
                loader.textContent = 'Loading scores...';
                loader.style.display = 'block';
            }} else {{
                loader.textContent = '⏳';
                loader.style.display = 'block';
            }}

            try {{
                // Fetch user team
                if (firstLoad) {{
                    let teamRes = await fetch('/user-team-data?match_id={match_id}');
                    userTeam = await teamRes.json();
                }}

                // Fetch scores
                let res = await fetch('/match-score-data?match_id={match_id}');
                let data = await res.json();

                if (data.error) {{
                    document.getElementById("players-table").innerHTML = '<p>' + data.error + '</p>';
                    document.getElementById("contestants-table").innerHTML = '<p>' + data.error + '</p>';
                    loader.style.display = 'none';
                    return;
                }}

                // Build players table
                let playersHTML = `
                                  <table>
                                  <thead>
                                  <tr>
                                  <th>Name</th>
                                  <th>Team</th>
                                  <th>Role</th>
                                  <th>Runs</th>
                                  <th>Balls</th>
                                  <th>4s</th>
                                  <th>6s</th>
                                  <th>SR</th>
                                  <th>Overs</th>
                                  <th>Maidens</th>
                                  <th>Wkts</th>
                                  <th>B/LBW</th>
                                  <th>Eco</th>
                                  <th>Catches</th>
                                  <th>RO+St</th>
                                  <th>RO Ind</th>
                                  <th style="font-weight: bold; color: #2e7d32;">Points</th>
                                  </tr>
                                  </thead>
                                  <tbody>`;
                data.players.forEach(p => {{
                    let rowClass = userTeam.includes(p.name) ? 'user-team' : '';
                    playersHTML += `<tr class="${{rowClass}}">
                                    <td>${{p.name}}</td>
                                    <td>${{p.team}}</td>
                                    <td>${{p.role}}</td>
                                    <td>${{p.runs || 0}}</td>
                                    <td>${{p.balls || 0}}</td>
                                    <td>${{p.fours || 0}}</td>
                                    <td>${{p.sixes || 0}}</td>
                                    <td>${{p.strike_rate || 0}}</td>
                                    <td>${{p.overs || 0}}</td>
                                    <td>${{p.maidens || 0}}</td>
                                    <td>${{p.wickets || 0}}</td>
                                    <td>${{(p.bowled || 0) + (p.lbw || 0)}}</td>
                                    <td>${{p.economy || 0}}</td>
                                    <td>${{p.catches || 0}}</td>
                                    <td>${{(p.runout_direct || 0) + (p.stumpings || 0)}}</td>
                                    <td>${{p.runout_indirect || 0}}</td>
                                    <td style="font-weight: bold;">${{p.points.toFixed(2)}}</td>
                                    </tr>`;
                }});
                playersHTML += '</tbody></table>';
                document.getElementById("players-table").innerHTML = playersHTML;

                // Build contestants table
                let contestantsHTML = '<table><thead><tr><th>Contestant</th><th>Points</th></tr></thead><tbody>';
                data.contestants.forEach(c => {{
                    contestantsHTML += `<tr><td>${{c.name}}</td><td>${{c.points.toFixed(2)}}</td></tr>`;
                }});
                contestantsHTML += '</tbody></table>';
                document.getElementById("contestants-table").innerHTML = contestantsHTML;

                loader.style.display = 'none';

                if (firstLoad) {{
                    firstLoad = false;
                }}

            }} catch (e) {{
                console.log("Error loading scores", e);
                loader.textContent = 'Error loading scores. Please try again.';
                if (firstLoad) {{
                    firstLoad = false;
                }}
            }}
        }}

        // Initial load
        loadScores();

        // Auto refresh every 30 sec
        setInterval(loadScores, 30000);
        </script>
        """
    
        return html
        
    
    
    @app.on_event("startup")
    def startup():
    
        try:
            players_data = players_sheet.get_all_records()
            matches_data = matches_sheet.get_all_records()
            teams_data = teams_sheet.get_all_records()
    
            tournament.initialize(players_data, matches_data, teams_data)
    
            tournament.start_scheduler()
        except Exception as e:
            print("ERROR DURING STARTUP:")
            traceback.print_exc()
        
    @app.get("/leaderboard", response_class=HTMLResponse)
    def leaderboard(request: Request):
        current_user = request.session.get('name', '')

        body = f"""
        <h2>Leaderboard</h2>
        <p class="muted">Live standings across all contestants.</p>
        <div id="loader" class="message success">Loading leaderboard...</div>
        <div id="leaderboard" class="table-scroll" style="display:none;"></div>
        <a class="back-link" href='/dashboard'>Back to dashboard</a>
        <script>
            async function loadLeaderboard() {{
                const loader = document.getElementById('loader');
                const board = document.getElementById('leaderboard');
                const currentUser = "{current_user}";

                loader.style.display = 'block';
                board.style.display = 'none';

                try {{
                    const res = await fetch('/leaderboard-data');
                    let data = await res.json();

                    if (!Array.isArray(data) || data.length === 0) {{
                        board.innerHTML = '<p>No leaderboard data available</p>';
                        loader.style.display = 'none';
                        board.style.display = 'block';
                        return;
                    }}

                    data.sort((a, b) => parseFloat(b.points) - parseFloat(a.points));

                    let tableHTML = '<table id="leaderboard-table"><thead><tr><th>#</th><th>Contestant</th><th>Points</th></tr></thead><tbody>';

                    data.forEach((user, index) => {{
                        const rowClass = user.name === currentUser ? 'current-user-row' : '';
                        tableHTML += `<tr class="${{rowClass}}"><td>${{index + 1}}</td><td>${{user.name}}</td><td>${{parseFloat(user.points).toFixed(2)}}</td></tr>`;
                    }});

                    tableHTML += '</tbody></table>';
                    board.innerHTML = tableHTML;
                    loader.style.display = 'none';
                    board.style.display = 'block';

                }} catch (e) {{
                    console.log('Error loading leaderboard', e);
                    loader.textContent = 'Error loading leaderboard. Please try again.';
                }}
            }}

            loadLeaderboard();
            setInterval(loadLeaderboard, 15000);
        </script>
        """

        return render_page("Leaderboard", body)

        html = f"""
        <h2>🏆 Leaderboard</h2>

        <div id="loader">Loading leaderboard...</div>
        <div id="leaderboard" style="overflow-x:auto; display:none; max-width:100%;"></div>

        <br><a href='/dashboard'>⬅ Back</a>

        <style>
            #leaderboard-table {{
                border-collapse: collapse;
                width: 100%;
                min-width: 500px;
            }}
            #leaderboard-table th, #leaderboard-table td {{
                border: 1px solid #ccc;
                padding: 10px;
                text-align: left;
            }}
            #leaderboard-table th {{
                background: #f4f4f8;
            }}
            #leaderboard-table tr:nth-child(even) {{
                background: #fafafa;
            }}
            .current-user-row {{
                background: #fff3cd;
                font-weight: bold;
            }}
            .user-team {{
                background-color: #fff3cd; /* light yellow */
                font-weight: 600;
            }}
        </style>

        <script>
            async function loadLeaderboard() {{
                const loader = document.getElementById('loader');
                const board = document.getElementById('leaderboard');
                const currentUser = "{current_user}";

                loader.style.display = 'block';
                board.style.display = 'none';

                try {{
                    const res = await fetch('/leaderboard-data');
                    let data = await res.json();

                    if (!Array.isArray(data) || data.length === 0) {{
                        board.innerHTML = '<p>No leaderboard data available</p>';
                        loader.style.display = 'none';
                        board.style.display = 'block';
                        return;
                    }}

                    // Sort descending by points
                    data.sort((a, b) => parseFloat(b.points) - parseFloat(a.points));

                    let tableHTML = '<table id="leaderboard-table"><thead><tr><th>#</th><th>Contestant</th><th>Points</th></tr></thead><tbody>'; 

                    data.forEach((user, index) => {{
                        const rowClass = user.name === currentUser ? 'current-user-row' : '';
                        tableHTML += `<tr class="${{rowClass}}"><td>${{index + 1}}</td><td>${{user.name}}</td><td>${{parseFloat(user.points).toFixed(2)}}</td></tr>`;
                    }});

                    tableHTML += '</tbody></table>';

                    board.innerHTML = tableHTML;
                    loader.style.display = 'none';
                    board.style.display = 'block';

                }} catch (e) {{
                    console.log('Error loading leaderboard', e);
                    loader.textContent = 'Error loading leaderboard. Please try again.';
                }}
            }}

            loadLeaderboard();
            setInterval(loadLeaderboard, 15000);
        </script>
        """

        return html
        
        
    @app.get("/points-table", response_class=HTMLResponse)
    def points_table(request: Request):
        current_user = request.session.get('name', '')

        body = f"""
        <h2>Match-wise Points Table</h2>
        <p class="muted">Swipe horizontally on mobile to compare every contestant match by match.</p>
        <div id="loader" class="message success">Loading points table...</div>
        <div id="points-container" class="table-scroll" style="display:none;"></div>
        <a class="back-link" href='/dashboard'>Back to dashboard</a>
        <script>
        async function loadPointsTable() {{
            const loader = document.getElementById('loader');
            const container = document.getElementById('points-container');
            const currentUser = "{current_user}";

            loader.style.display = 'block';
            container.style.display = 'none';

            try {{
                const res = await fetch('/points-table-data');
                const data = await res.json();

                if (!Array.isArray(data) || data.length === 0) {{
                    loader.textContent = 'No data available';
                    return;
                }}

                const contestants = [...new Set(data.map(r => r.User))].sort();
                const matches = [...new Set(data.map(r => r.MatchID))].sort((a, b) => Number(a) - Number(b));

                const pointsLookup = {{}};
                data.forEach(r => {{
                    const matchId = String(r.MatchID);
                    const user = r.User;
                    const points = parseFloat(r.Points) || 0;

                    if (!pointsLookup[matchId]) pointsLookup[matchId] = {{}};
                    pointsLookup[matchId][user] = points;
                }});

                let tableHTML = '<table id="points-table"><thead><tr><th>Match</th>';
                contestants.forEach(user => {{
                    const thClass = user === currentUser ? 'current-user-column' : '';
                    tableHTML += `<th class="${{thClass}}">${{user}}</th>`;
                }});
                tableHTML += '</tr></thead><tbody>';

                matches.forEach(matchId => {{
                    tableHTML += `<tr><td><b>${{matchId}}</b></td>`;

                    contestants.forEach(user => {{
                        const value = pointsLookup[matchId]?.[user] ?? 0;
                        const tdClass = user === currentUser ? 'current-user-column' : '';
                        tableHTML += `<td class="${{tdClass}}">${{value.toFixed(2)}}</td>`;
                    }});

                    tableHTML += '</tr>';
                }});

                tableHTML += '<tfoot><tr><td><b>Total</b></td>';
                contestants.forEach(user => {{
                    let userTotal = 0;
                    matches.forEach(matchId => {{
                        userTotal += pointsLookup[matchId]?.[user] ?? 0;
                    }});
                    const tdClass = user === currentUser ? 'current-user-column' : '';
                    tableHTML += `<td class="${{tdClass}}"><b>${{userTotal.toFixed(2)}}</b></td>`;
                }});
                tableHTML += '</tr></tfoot>';

                tableHTML += '</tbody></table>';
                container.innerHTML = tableHTML;
                loader.style.display = 'none';
                container.style.display = 'block';

            }} catch (e) {{
                console.error('Error loading points table', e);
                loader.textContent = 'Error loading points table. Please try again.';
            }}
        }}

        loadPointsTable();
        </script>
        """

        return render_page("Points Table", body)

        html = f"""
        <h2>📊 Match-wise Points Table</h2>

        <div id="loader">Loading points table...</div>
        <div id="points-container" style="overflow-x:auto; display:none; max-width:100%;"></div>

        <br><a href='/dashboard'>⬅ Back</a>

        <style>
            #points-table {{
                border-collapse: collapse;
                width: 100%;
                min-width: 700px;
            }}
            #points-table th, #points-table td {{
                border: 1px solid #ccc;
                padding: 8px;
                text-align: center;
                white-space: nowrap;
            }}
            #points-table th {{
                background: #f4f4f8;
            }}
            #points-table tr:nth-child(even) {{
                background: #fafafa;
            }}
            #points-table tfoot td {{
                font-weight: bold;
                background: #eeffee;
            }}
            .current-user-column {{
                background: #fff3cd;
                font-weight: bold;
            }}
        </style>

        <script>
        async function loadPointsTable() {{
            const loader = document.getElementById('loader');
            const container = document.getElementById('points-container');
            const currentUser = "{current_user}";

            loader.style.display = 'block';
            container.style.display = 'none';

            try {{
                const res = await fetch('/points-table-data');
                const data = await res.json();

                if (!Array.isArray(data) || data.length === 0) {{
                    loader.textContent = 'No data available';
                    return;
                }}

                const contestants = [...new Set(data.map(r => r.User))].sort();
                const matches = [...new Set(data.map(r => r.MatchID))].sort((a, b) => Number(a) - Number(b));

                const pointsLookup = {{}};
                data.forEach(r => {{
                    const matchId = String(r.MatchID);
                    const user = r.User;
                    const points = parseFloat(r.Points) || 0;

                    if (!pointsLookup[matchId]) pointsLookup[matchId] = {{}};
                    pointsLookup[matchId][user] = points;
                }});

                let tableHTML = '<table id="points-table"><thead><tr><th>Match</th>';
                contestants.forEach(user => {{
                    const thClass = user === currentUser ? 'current-user-column' : '';
                    tableHTML += `<th class="${{thClass}}">${{user}}</th>`;
                }});
                tableHTML += '</tr></thead><tbody>';

                matches.forEach(matchId => {{
                    tableHTML += `<tr><td><b>${{matchId}}</b></td>`;

                    contestants.forEach(user => {{
                        const value = pointsLookup[matchId]?.[user] ?? 0;
                        const tdClass = user === currentUser ? 'current-user-column' : '';
                        tableHTML += `<td class="${{tdClass}}">${{value.toFixed(2)}}</td>`;
                    }});

                    tableHTML += '</tr>';
                }});

                // Add totals row
                tableHTML += '<tfoot><tr><td><b>Total</b></td>';
                contestants.forEach(user => {{
                    let userTotal = 0;
                    matches.forEach(matchId => {{
                        userTotal += pointsLookup[matchId]?.[user] ?? 0;
                    }});
                    const tdClass = user === currentUser ? 'current-user-column' : '';
                    tableHTML += `<td class="${{tdClass}}"><b>${{userTotal.toFixed(2)}}</b></td>`;
                }});
                tableHTML += '</tr></tfoot>';

                tableHTML += '</tbody></table>';

                container.innerHTML = tableHTML;
                loader.style.display = 'none';
                container.style.display = 'block';

            }} catch (e) {{
                console.error('Error loading points table', e);
                loader.textContent = 'Error loading points table. Please try again.';
            }}
        }}

        loadPointsTable();
        </script>
        """

        return html

    @app.get('/points-table-data')
    def points_table_data():
        try:
            sheet = client.open('FantasyCricket').worksheet('ContestantPoints')
            data = sheet.get_all_records()
            return JSONResponse(data)
        except Exception:
            return JSONResponse([])
    
    @app.get("/leaderboard-data")
    def leaderboard_data():
    
        try:
            sheet = client.open("FantasyCricket").worksheet("ContestantPoints")
            data = sheet.get_all_records()
        except:
            return JSONResponse([])
    
        totals = {}
    
        for row in data:
            mobile = str(row["Mobile"])
            name = row["User"]
            pts = float(row["Points"])
    
            if mobile not in totals:
                totals[mobile] = {"name": name, "points": 0}
    
            totals[mobile]["points"] += pts
    
        sorted_users = sorted(
            totals.values(),
            key=lambda x: x["points"],
            reverse=True
        )
    
        return JSONResponse(sorted_users)
    
    @app.get("/user-team-data")
    def user_team_data(request: Request, match_id: str):
        mobile = request.session.get('mobile')
        if not mobile:
            return JSONResponse([])
        
        try:
            teams_sheet = client.open("FantasyCricket").worksheet("Teams")
            teams_data = teams_sheet.get_all_records()
        except:
            return JSONResponse([])
        
        user_team = []
        for row in teams_data:
            if str(row["Mobile"]) == str(mobile) and str(row["MatchID"]) == str(match_id):
                user_team.append(row["Name"])
        
        return JSONResponse(user_team)
    
    @app.get("/match-score-data")
    def match_score_data(match_id: str):
        #tournament.compute_player_points_for_match(match_id)
        matches = get_cached_data("matches")
        match_row = next((m for m in matches if str(m["MatchID"]) == str(match_id)), None)
    
        if not match_row:
            return JSONResponse({"error": "Match not found"})
    
        players_data = get_cached_data("players")
        registry = PlayerRegistry(players_data)
    
        match_obj = Match(
            match_id,
            clean_team_name(match_row["Team1"]),
            clean_team_name(match_row["Team2"]),
            registry
        )
        print("Parsed players:", len(match_obj.players))
    
    
        match_code = int(match_id) + MATCH_CODE_OFFSET
        html_content = fetch_scorecard_html(match_code)
    
        if not html_content:
            return JSONResponse({"error": "No data"})
    
        # ✅ FIX HERE
        soup = BeautifulSoup(html_content, "html.parser")
        match_obj.parse_scorecard(soup)
    
        players = match_obj.players
        
        # Get player points for this match
        player_points = {}
        player_role = {}
        try:
            points_sheet = client.open("FantasyCricket").worksheet("PlayerPoints")
            points_data = points_sheet.get_all_records()
            for row in points_data:
                if str(row["MatchID"]) == str(match_id):
                    pid = str(row["PlayerID"]).strip()
                    player_points[pid] = float(row["Points"])
                    player_role[pid] = row["Role"]
        except:
            pass
        
        result = []
    
        for p in players.values():
            player_id = str(p.player_id) if hasattr(p, 'player_id') else None
            points = player_points.get(player_id, 0)
            role = player_role.get(player_id, None)
            result.append({
                    "name": p.name,
                    "team": p.team,
                    "role": role,
                    "runs": p.runs,
                    "balls": p.balls,
                    "fours": p.fours,
                    "sixes": p.sixes,
                    "strike_rate": p.strike_rate,
                    "overs": p.overs,
                    "maidens": p.maidens,
                    "runs_conceded": p.runs_conceded,
                    "wickets": p.wickets,
                    "bowled": p.bowled,
                    "lbw": p.lbw,
                    "economy": p.economy,
                    "catches": p.catches,
                    "runout_direct": p.runout_direct,
                    "stumpings": p.stumpings,
                    "runout_indirect": p.runout_indirect,
                    "points": points
            })
        
        # Sort players by points descending
        result.sort(key=lambda x: x["points"], reverse=True)
        
        # Get contestants for this match
        contestants = []
        try:
            sheet = client.open('FantasyCricket').worksheet('ContestantPoints')
            all_points = sheet.get_all_records()
            for row in all_points:
                if str(row['MatchID']) == str(match_id):
                    contestants.append({
                        'name': row['User'],
                        'points': float(row['Points'])
                    })
        except:
            pass
        
        # Sort contestants by points descending
        contestants.sort(key=lambda x: x['points'], reverse=True)
        
        return JSONResponse({"players": result, "contestants": contestants})
        
    @app.get("/debug")
    def debug():
    
        for match_id in tournament.matches:
            tournament.update_match_data(match_id)
    
        tournament.compute_all_points()
    
        return [
            {
                "name": c.name,
                "points": c.points
            }
            for c in tournament.contestants.values()
        ]
    
    @app.get("/health")
    def health():
        return {"status": "ok"}

except Exception as e:
    print("❌ STARTUP ERROR:")
    traceback.print_exc()
    raise e
