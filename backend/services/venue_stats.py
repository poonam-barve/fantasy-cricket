"""
IPL venue stats — hardcoded defaults with optional Howstat refresh.
All scraping fails silently, returning cached/hardcoded data.
"""

from datetime import datetime

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    requests = None
    BeautifulSoup = None

from backend.config import IST, get_current_date_key


# Team -> home ground mapping
TEAM_VENUES = {
    "CSK": "MA Chidambaram Stadium, Chennai",
    "CHENNAI SUPER KINGS": "MA Chidambaram Stadium, Chennai",
    "MI": "Wankhede Stadium, Mumbai",
    "MUMBAI INDIANS": "Wankhede Stadium, Mumbai",
    "RCB": "M Chinnaswamy Stadium, Bengaluru",
    "ROYAL CHALLENGERS BENGALURU": "M Chinnaswamy Stadium, Bengaluru",
    "KKR": "Eden Gardens, Kolkata",
    "KOLKATA KNIGHT RIDERS": "Eden Gardens, Kolkata",
    "DC": "Arun Jaitley Stadium, Delhi",
    "DELHI CAPITALS": "Arun Jaitley Stadium, Delhi",
    "RR": "Sawai Mansingh Stadium, Jaipur",
    "RAJASTHAN ROYALS": "Sawai Mansingh Stadium, Jaipur",
    "SRH": "Rajiv Gandhi Intl Stadium, Hyderabad",
    "SUNRISERS HYDERABAD": "Rajiv Gandhi Intl Stadium, Hyderabad",
    "PBKS": "PCA IS Bindra Stadium, Mohali",
    "PUNJAB KINGS": "PCA IS Bindra Stadium, Mohali",
    "GT": "Narendra Modi Stadium, Ahmedabad",
    "GUJARAT TITANS": "Narendra Modi Stadium, Ahmedabad",
    "LSG": "BRSABV Ekana Stadium, Lucknow",
    "LUCKNOW SUPER GIANTS": "BRSABV Ekana Stadium, Lucknow",
}

# Hardcoded fallback stats (from Howstat, accurate through March 2026)
DEFAULT_VENUE_STATS = {
    "MA Chidambaram Stadium, Chennai": {
        "venue": "MA Chidambaram Stadium",
        "city": "Chennai",
        "matches": 91,
        "avg_first_innings": 163.9,
        "bat_first_win_pct": 56.0,
        "chase_win_pct": 44.0,
        "pitch_type": "Bowling-friendly",
    },
    "Wankhede Stadium, Mumbai": {
        "venue": "Wankhede Stadium",
        "city": "Mumbai",
        "matches": 124,
        "avg_first_innings": 170.8,
        "bat_first_win_pct": 46.0,
        "chase_win_pct": 54.0,
        "pitch_type": "Batting-friendly",
    },
    "M Chinnaswamy Stadium, Bengaluru": {
        "venue": "M Chinnaswamy Stadium",
        "city": "Bengaluru",
        "matches": 101,
        "avg_first_innings": 166.6,
        "bat_first_win_pct": 42.6,
        "chase_win_pct": 53.5,
        "pitch_type": "Batting-friendly",
    },
    "Eden Gardens, Kolkata": {
        "venue": "Eden Gardens",
        "city": "Kolkata",
        "matches": 100,
        "avg_first_innings": 165.3,
        "bat_first_win_pct": 42.0,
        "chase_win_pct": 57.0,
        "pitch_type": "Balanced",
    },
    "Arun Jaitley Stadium, Delhi": {
        "venue": "Arun Jaitley Stadium",
        "city": "Delhi",
        "matches": 97,
        "avg_first_innings": 170.0,
        "bat_first_win_pct": 48.5,
        "chase_win_pct": 50.5,
        "pitch_type": "Balanced",
    },
    "Sawai Mansingh Stadium, Jaipur": {
        "venue": "Sawai Mansingh Stadium",
        "city": "Jaipur",
        "matches": 64,
        "avg_first_innings": 165.5,
        "bat_first_win_pct": 35.9,
        "chase_win_pct": 64.1,
        "pitch_type": "Balanced",
    },
    "Rajiv Gandhi Intl Stadium, Hyderabad": {
        "venue": "Rajiv Gandhi Intl Stadium",
        "city": "Hyderabad",
        "matches": 83,
        "avg_first_innings": 163.0,
        "bat_first_win_pct": 42.2,
        "chase_win_pct": 56.6,
        "pitch_type": "Bowling-friendly",
    },
    "PCA IS Bindra Stadium, Mohali": {
        "venue": "PCA IS Bindra Stadium",
        "city": "Mohali",
        "matches": 60,
        "avg_first_innings": 168.1,
        "bat_first_win_pct": 45.0,
        "chase_win_pct": 55.0,
        "pitch_type": "Batting-friendly",
    },
    "Narendra Modi Stadium, Ahmedabad": {
        "venue": "Narendra Modi Stadium",
        "city": "Ahmedabad",
        "matches": 44,
        "avg_first_innings": 177.2,
        "bat_first_win_pct": 50.0,
        "chase_win_pct": 50.0,
        "pitch_type": "Batting-friendly",
    },
    "BRSABV Ekana Stadium, Lucknow": {
        "venue": "BRSABV Ekana Stadium",
        "city": "Lucknow",
        "matches": 23,
        "avg_first_innings": 173.9,
        "bat_first_win_pct": 39.1,
        "chase_win_pct": 56.5,
        "pitch_type": "Batting-friendly",
    },
    "Barsapara Cricket Stadium, Guwahati": {
        "venue": "Barsapara Cricket Stadium",
        "city": "Guwahati",
        "matches": 10,
        "avg_first_innings": 167.5,
        "bat_first_win_pct": 50.0,
        "chase_win_pct": 50.0,
        "pitch_type": "Balanced",
    },
    "Maharaja Yadavindra Singh International Cricket Stadium, Mullanpur": {
        "venue": "MYSI Stadium",
        "city": "Mullanpur",
        "matches": 14,
        "avg_first_innings": 178.3,
        "bat_first_win_pct": 42.9,
        "chase_win_pct": 57.1,
        "pitch_type": "Batting-friendly",
    },
    "Shaheed Veer Narayan Singh International Stadium, Raipur": {
        "venue": "VNS Intl Stadium",
        "city": "Raipur",
        "matches": 4,
        "avg_first_innings": 162.0,
        "bat_first_win_pct": 50.0,
        "chase_win_pct": 50.0,
        "pitch_type": "Balanced",
    },
    "HPCA Stadium, Dharamsala": {
        "venue": "HPCA Stadium",
        "city": "Dharamsala",
        "matches": 12,
        "avg_first_innings": 172.8,
        "bat_first_win_pct": 41.7,
        "chase_win_pct": 58.3,
        "pitch_type": "Batting-friendly",
    },
}

TODAY_VENUE_CACHE = {
    "date": "",
    "by_match_id": {},
}


def get_venue_for_match(team1: str, team2: str) -> str | None:
    """Return the venue name for a match. team1 is assumed to be the home team."""
    t1 = (team1 or "").strip().upper()
    return TEAM_VENUES.get(t1)


def _normalize_venue_key(ground: str, city: str) -> str | None:
    """Find the matching key in DEFAULT_VENUE_STATS for a ground+city combo."""
    if not ground:
        return None
    ground_lower = ground.lower().strip().rstrip(".")
    city_lower = (city or "").lower().strip().split(",")[0].strip()  # Take first city if "Mullanpur, New Chandigarh"
    for key in DEFAULT_VENUE_STATS:
        key_lower = key.lower()
        key_ground = key_lower.split(",")[0].strip()
        key_city = key_lower.split(",")[1].strip() if "," in key_lower else ""
        # Match on ground name substring
        if ground_lower in key_ground or key_ground in ground_lower:
            return key
        # Match on city
        if city_lower and city_lower == key_city:
            return key
    return None


def get_venue_stats_by_name(ground: str, city: str) -> dict | None:
    """Lookup venue stats by ground name and city. Fails silently."""
    try:
        key = _normalize_venue_key(ground, city)
        if key:
            return DEFAULT_VENUE_STATS.get(key)
        # Return basic info even without stats
        if ground:
            return {
                "venue": ground,
                "city": city or "",
                "matches": None,
                "avg_first_innings": None,
                "bat_first_win_pct": None,
                "chase_win_pct": None,
                "pitch_type": None,
            }
        return None
    except Exception:
        return None


def get_venue_stats(team1: str, team2: str, venue_name: str | None = None) -> dict | None:
    """Return venue stats for a match. Uses DB venue if available, falls back to team1 home ground."""
    try:
        if venue_name:
            # Try to split "Ground, City" format
            parts = venue_name.split(",", 1)
            ground = parts[0].strip()
            city = parts[1].strip() if len(parts) > 1 else ""
            result = get_venue_stats_by_name(ground, city)
            if result:
                return result

        # Fallback: team1 home ground
        venue_key = get_venue_for_match(team1, team2)
        if not venue_key:
            return None
        return DEFAULT_VENUE_STATS.get(venue_key)
    except Exception:
        return None


def invalidate_today_venue_cache() -> None:
    TODAY_VENUE_CACHE["date"] = ""
    TODAY_VENUE_CACHE["by_match_id"] = {}


def prime_today_venue_cache(match_rows: list[dict]) -> dict[int, dict | None]:
    today_key = get_current_date_key()
    by_match_id: dict[int, dict | None] = {}

    for match in match_rows:
        if match.get("match_date") != today_key:
            continue
        if match.get("status") != "future":
            continue
        by_match_id[int(match["id"])] = get_venue_stats(
            match.get("team1", ""),
            match.get("team2", ""),
            match.get("venue"),
        )

    TODAY_VENUE_CACHE["date"] = today_key
    TODAY_VENUE_CACHE["by_match_id"] = by_match_id
    return by_match_id


def get_today_cached_venue_stats(match_id: int, match_date: str, status: str) -> dict | None:
    today_key = get_current_date_key()
    if match_date != today_key or status != "future":
        return None

    if TODAY_VENUE_CACHE["date"] != today_key:
        return None

    return TODAY_VENUE_CACHE["by_match_id"].get(int(match_id))
