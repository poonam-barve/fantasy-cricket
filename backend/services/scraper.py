import json
import re
import time
import threading
from datetime import datetime, timedelta
import requests
from difflib import SequenceMatcher
from bs4 import BeautifulSoup

from backend.config import (
    CRICBUZZ_IPL_SERIES_ID,
    CRICBUZZ_IPL_SERIES_SLUG,
    ESPN_SERIES_ID,
    ESPN_IPL_SERIES_ID,
    ESPN_IPL_SERIES_SLUG,
    ESPN_MATCH_ID_OFFSET,
    IST,
    TEAM_MAP,
    get_current_datetime,
)
from backend.models.registry import PlayerRegistry
from backend.services import data_service
from backend.services.cache_locks import acquire_cache_locks, get_cache_lock


CRICBUZZ_MATCH_ID_MAP: dict[int, int] = {}
ESPN_MATCH_ID_MAP: dict[int, int] = {}
PLAYING_XI_CACHE: dict[int, dict] = {}
PLAYING_XI_TTL_SECONDS = 60
PLAYING_XI_REFRESH_INFLIGHT: set[int] = set()
PLAYING_XI_REFRESH_LOCK = threading.Lock()
TOSS_INFO_CACHE: dict[int, dict] = {}
TOSS_INFO_TTL_SECONDS = 60
PLAYING_XI_CACHE_LOCK = get_cache_lock("scraper_playing_xi")
TOSS_INFO_CACHE_LOCK = get_cache_lock("scraper_toss_info")
LAST_ESPN_SCORECARD_URL: dict[int, str] = {}
_ESPN_SESSION = requests.Session()
_ESPN_SESSION.trust_env = False
_ESPN_SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://www.espn.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }
)


def _session_get(url):
    return _ESPN_SESSION.get(url, timeout=20)


def _copy_playing_xi_payload(payload: dict) -> dict:
    return {
        "announced": bool(payload.get("announced")),
        "url": payload.get("url", ""),
        "player_ids": list(payload.get("player_ids", [])),
        "substitute_ids": list(payload.get("substitute_ids", [])),
    }


def _get_cached_playing_xi_payload(match_id: int) -> dict | None:
    with PLAYING_XI_CACHE_LOCK:
        cached = PLAYING_XI_CACHE.get(int(match_id))
        if not cached:
            return None
        return _copy_playing_xi_payload(cached.get("payload") or {})


def _copy_toss_payload(payload: dict) -> dict:
    return {
        "announced": bool(payload.get("announced")),
        "team": payload.get("team"),
        "decision": payload.get("decision"),
        "text": payload.get("text", ""),
        "url": payload.get("url", ""),
    }


def _is_finalized_playing_xi(payload: dict) -> bool:
    return len(payload.get("player_ids", [])) == 22 and len(payload.get("substitute_ids", [])) == 10


def _is_playing_xi_announced(payload: dict) -> bool:
    return len(payload.get("player_ids", [])) == 22


def _merge_playing_xi_payloads(primary: dict | None, secondary: dict | None) -> dict:
    merged = {
        "announced": False,
        "url": "",
        "player_ids": [],
        "substitute_ids": [],
        "unmatched_names": [],
        "substitute_unmatched_names": [],
        "source": "",
        "substitutes_available": False,
        "finalized": False,
    }

    for candidate in (primary, secondary):
        if not candidate:
            continue
        if candidate.get("url"):
            merged["url"] = candidate.get("url") or merged["url"]
        if candidate.get("source"):
            merged["source"] = candidate.get("source") or merged["source"]

        for key in ("player_ids", "substitute_ids"):
            combined = list(merged[key])
            for pid in candidate.get(key, []) or []:
                if pid not in combined:
                    combined.append(pid)
            merged[key] = combined

        for key in ("unmatched_names", "substitute_unmatched_names"):
            combined_names = list(merged[key])
            for name in candidate.get(key, []) or []:
                if name not in combined_names:
                    combined_names.append(name)
            merged[key] = combined_names

        merged["substitutes_available"] = merged["substitutes_available"] or bool(candidate.get("substitutes_available"))

    merged["announced"] = len(merged["player_ids"]) == 22
    merged["finalized"] = _is_finalized_playing_xi(merged)
    return merged


def _parse_match_datetime(match_date: str | None, match_time: str | None):
    if not match_date or not match_time:
        return None

    try:
        match_start = IST.localize(datetime.strptime(f"{match_date} {match_time}", "%Y-%m-%d %H:%M"))
    except Exception:
        return None
    return match_start


def compute_toss_time(match_date: str | None, match_time: str | None) -> str | None:
    match_start = _parse_match_datetime(match_date, match_time)
    if not match_start:
        return None
    return (match_start - timedelta(minutes=30)).strftime("%H:%M")


def _resolve_window_start(match_date: str | None, match_time: str | None, toss_time: str | None = None):
    if toss_time:
        try:
            parsed = datetime.strptime(toss_time, "%H:%M")
            if match_date:
                return IST.localize(datetime.strptime(f"{match_date} {parsed.strftime('%H:%M')}", "%Y-%m-%d %H:%M"))
        except Exception:
            try:
                return IST.localize(datetime.strptime(toss_time, "%Y-%m-%d %H:%M"))
            except Exception:
                pass
    match_start = _parse_match_datetime(match_date, match_time)
    if not match_start:
        return None
    return match_start - timedelta(minutes=30)


def _should_attempt_playing_xi_fetch(match_date: str | None, match_time: str | None, toss_time: str | None = None) -> bool:
    match_start = _parse_match_datetime(match_date, match_time)
    if not match_start:
        return True

    window_start = _resolve_window_start(match_date, match_time, toss_time)
    if not window_start:
        return True

    return get_current_datetime() >= window_start


def should_attempt_toss_fetch(match_date: str | None, match_time: str | None, toss_time: str | None = None) -> bool:
    match_start = _parse_match_datetime(match_date, match_time)
    if not match_start:
        return False

    window_start = _resolve_window_start(match_date, match_time, toss_time)
    if not window_start:
        return False

    now = get_current_datetime()
    return window_start <= now < match_start


def _is_before_match_start(match_date: str | None, match_time: str | None) -> bool:
    match_start = _parse_match_datetime(match_date, match_time)
    if not match_start:
        return False

    return get_current_datetime() < match_start


def _playing_xi_refresh_inflight(match_id: int) -> bool:
    with PLAYING_XI_REFRESH_LOCK:
        return int(match_id) in PLAYING_XI_REFRESH_INFLIGHT


def _acquire_playing_xi_refresh(match_id: int) -> bool:
    with PLAYING_XI_REFRESH_LOCK:
        match_key = int(match_id)
        if match_key in PLAYING_XI_REFRESH_INFLIGHT:
            return False
        PLAYING_XI_REFRESH_INFLIGHT.add(match_key)
        return True


def _release_playing_xi_refresh(match_id: int) -> None:
    with PLAYING_XI_REFRESH_LOCK:
        PLAYING_XI_REFRESH_INFLIGHT.discard(int(match_id))


def refresh_playing_xi_async(
    match_id: int,
    team1: str,
    team2: str,
    players_rows: list[dict],
    match_date: str | None = None,
    match_time: str | None = None,
    toss_time: str | None = None,
) -> bool:
    """Schedule a background Playing XI refresh if one is not already running."""
    if not _acquire_playing_xi_refresh(match_id):
        return False

    def _run():
        try:
            refresh_playing_xi_cache(
                match_id,
                team1,
                team2,
                players_rows,
                match_date=match_date,
                match_time=match_time,
                toss_time=toss_time,
            )
        except Exception as exc:
            print(f"[Playing XI] Match {match_id}: async refresh failed: {exc}")
        finally:
            _release_playing_xi_refresh(match_id)

    threading.Thread(target=_run, daemon=True, name=f"playing-xi-refresh-{int(match_id)}").start()
    return True


def refresh_playing_xi_cache(
    match_id: int,
    team1: str,
    team2: str,
    players_rows: list[dict],
    match_date: str | None = None,
    match_time: str | None = None,
    toss_time: str | None = None,
) -> dict:
    """Refresh and persist Playing XI data for scheduler/admin use."""
    if not _acquire_playing_xi_refresh(match_id):
        return _get_cached_playing_xi_payload(match_id) or {"announced": False, "url": "", "player_ids": [], "substitute_ids": []}

    try:
        return _fetch_playing_xi_impl(
            match_id,
            team1,
            team2,
            players_rows,
            match_date=match_date,
            match_time=match_time,
            toss_time=toss_time,
            force_refresh=True,
        )
    finally:
        _release_playing_xi_refresh(match_id)


def fetch_scorecard_html(match_id, team1: str | None = None, team2: str | None = None, match_date: str | None = None, force_refresh: bool = False):
    espn_match_id = None
    if team1 and team2:
        espn_match_id = data_service.get_stored_espn_match_id(int(match_id))
        if not espn_match_id or force_refresh:
            espn_match_id = resolve_espn_match_id(int(match_id), team1, team2, force_refresh=force_refresh)

    if not espn_match_id:
        try:
            espn_match_id = int(match_id)
        except Exception:
            return None

    def _try_fetch(resolved_match_id: int) -> str | None:
        weak_fallback_html: str | None = None
        strong_fallback_html: str | None = None
        attempted = 0
        successful = 0
        for url in build_espn_scorecard_url_variants(resolved_match_id):
            attempted += 1
            try:
                res = _session_get(url)
            except Exception as exc:
                continue

            if not (200 <= res.status_code < 300):
                continue

            quality = _espn_scorecard_html_quality(res.text, team1, team2)
            if quality >= 2:
                successful += 1
                strong_fallback_html = res.text
                LAST_ESPN_SCORECARD_URL[int(match_id)] = url
                return res.text
            if quality == 1 and weak_fallback_html is None:
                successful += 1
                weak_fallback_html = res.text
                LAST_ESPN_SCORECARD_URL[int(match_id)] = url
            elif weak_fallback_html is None:
                weak_fallback_html = res.text

        if strong_fallback_html:
            return strong_fallback_html

        if weak_fallback_html:
            return weak_fallback_html

        return None

    fetched_html = _try_fetch(int(espn_match_id))
    if fetched_html:
        return fetched_html

    if team1 and team2 and not force_refresh:
        refreshed_match_id = resolve_espn_match_id(int(match_id), team1, team2, force_refresh=True)
        if refreshed_match_id and refreshed_match_id != espn_match_id:
            fetched_html = _try_fetch(int(refreshed_match_id))
            if fetched_html:
                return fetched_html

    return None


def get_last_fetched_espn_scorecard_url(match_id: int) -> str | None:
    return LAST_ESPN_SCORECARD_URL.get(int(match_id))


def fetch_cricbuzz_scorecard_html(match_id: int, team1: str | None = None, team2: str | None = None):
    cricbuzz_match_id = CRICBUZZ_MATCH_ID_MAP.get(int(match_id)) or data_service.get_stored_cricbuzz_match_id(int(match_id))
    if not cricbuzz_match_id and team1 and team2:
        cricbuzz_match_id = resolve_cricbuzz_match_id(int(match_id), team1, team2)
    if not cricbuzz_match_id:
        print(f"[Cricbuzz Scorecard] Match {match_id}: no cached Cricbuzz match id found")
        return None

    url = f"https://www.cricbuzz.com/live-cricket-scorecard/{cricbuzz_match_id}"
    try:
        res = _session_get(url)
        if res.status_code != 200:
            print(f"[Cricbuzz Scorecard] Match {match_id}: status {res.status_code} for {url}")
            if team1 and team2:
                refreshed_match_id = resolve_cricbuzz_match_id(int(match_id), team1, team2, force_refresh=True)
                if refreshed_match_id and refreshed_match_id != cricbuzz_match_id:
                    refreshed_url = f"https://www.cricbuzz.com/live-cricket-scorecard/{refreshed_match_id}"
                    refreshed_res = _session_get(refreshed_url)
                    if refreshed_res.status_code == 200:
                        return refreshed_res.text
            return None
        return res.text
    except Exception as e:
        print(f"[Cricbuzz Scorecard] Match {match_id}: error fetching {url}: {e}")
        if team1 and team2:
            refreshed_match_id = resolve_cricbuzz_match_id(int(match_id), team1, team2, force_refresh=True)
            if refreshed_match_id and refreshed_match_id != cricbuzz_match_id:
                refreshed_url = f"https://www.cricbuzz.com/live-cricket-scorecard/{refreshed_match_id}"
                try:
                    refreshed_res = _session_get(refreshed_url)
                    if refreshed_res.status_code == 200:
                        return refreshed_res.text
                except Exception:
                    pass
        return None


def build_cricbuzz_schedule_url() -> str:
    return f"https://www.cricbuzz.com/cricket-series/{CRICBUZZ_IPL_SERIES_ID}/{CRICBUZZ_IPL_SERIES_SLUG}/matches"


def build_cricbuzz_playing_xi_url(cricbuzz_match_id: int) -> str:
    return f"https://www.cricbuzz.com/cricket-match-squads/{cricbuzz_match_id}"


def build_cricbuzz_commentary_url(cricbuzz_match_id: int) -> str:
    return f"https://www.cricbuzz.com/live-cricket-scores/{cricbuzz_match_id}"


def build_espn_schedule_url() -> str:
    return f"https://www.espn.in/cricket/scores/series/{ESPN_SERIES_ID}/season/2026/indian-premier-league"


def build_espn_scorecard_url(espn_match_id: int) -> str:
    return f"https://www.espn.com/cricket/series/{ESPN_SERIES_ID}/scorecard/{int(espn_match_id)}/utils"


def build_espn_scorecard_url_variants(espn_match_id: int) -> list[str]:
    match_id = int(espn_match_id)
    base_urls = [
        f"https://www.espn.com/cricket/series/{ESPN_SERIES_ID}/scorecard/{match_id}",
        f"https://www.espn.in/cricket/series/{ESPN_SERIES_ID}/scorecard/{match_id}",
    ]

    variants = []
    for base_url in base_urls:
        variants.extend([
            f"{base_url}/utils",
            base_url,
            f"{base_url}/crossDomain",
            f"{base_url}/Message",
        ])

    seen = set()
    ordered_variants = []
    for url in variants:
        if url in seen:
            continue
        seen.add(url)
        ordered_variants.append(url)
    return ordered_variants


def _espn_scorecard_html_quality(html_text: str | None, team1: str | None = None, team2: str | None = None) -> int:
    if not html_text:
        return 0

    text = " ".join(BeautifulSoup(html_text, "html.parser").stripped_strings)
    normalized = " ".join(text.lower().split())
    if not normalized:
        return 0

    if not any(marker in normalized for marker in ("batsmen", "bowling", "extras", "total", "scorecard")):
        return 0

    if any(marker in normalized for marker in ("0s", "dot balls", "dot-balls", "bowling o m r w econ")):
        return 2

    return 1


def _espn_scorecard_html_looks_useful(html_text: str | None, team1: str | None = None, team2: str | None = None) -> bool:
    return _espn_scorecard_html_quality(html_text, team1, team2) > 0


def _normalize_espn_match_key(match_id: int, team1: str, team2: str) -> tuple[int, frozenset[str]]:
    return (
        int(match_id),
        frozenset({_to_short_team_name(team1), _to_short_team_name(team2)}),
    )


def _fetch_espn_schedule_lookup() -> dict[tuple[int, frozenset[str]], int] | None:
    schedule_urls = [
        build_espn_schedule_url(),
        f"https://www.espn.com/cricket/scores/series/{ESPN_SERIES_ID}/season/2026/ipl",
        f"https://www.espn.com/cricket/scores/series/_/id/{ESPN_SERIES_ID}/season/2026/{ESPN_SERIES_ID}",
    ]
    match_no_regex = re.compile(r"\b(\d+)(?:st|nd|rd|th)\s+match\b", flags=re.IGNORECASE)

    def _teams_mentioned(text: str) -> set[str]:
        normalized = " ".join(text.lower().split())
        found: set[str] = set()
        for full_name, short_name in TEAM_MAP.items():
            if full_name == short_name:
                continue
            if full_name.lower() in normalized or short_name.lower() in normalized:
                found.add(short_name)
        return found

    for schedule_url in schedule_urls:
        try:
            print(f"[ESPN] Loading schedule mapping from {schedule_url}")
            res = _session_get(schedule_url)
            if res.status_code != 200:
                continue

            soup = BeautifulSoup(res.text, "html.parser")
            schedule_lookup: dict[tuple[int, frozenset[str]], int] = {}

            for anchor in soup.find_all("a", href=True):
                href = anchor.get("href", "")
                match_id_match = re.search(r"/cricket/series/\d+/(?:game|scorecard)/(\d+)/", href)
                if not match_id_match:
                    continue

                text_candidates = [
                    " ".join(anchor.stripped_strings),
                    " ".join(anchor.parent.stripped_strings) if anchor.parent else "",
                ]
                matched = False
                for text in text_candidates:
                    match_no_match = match_no_regex.search(text)
                    if not match_no_match:
                        continue

                    teams_found = _teams_mentioned(text)
                    if len(teams_found) != 2:
                        continue

                    match_no = int(match_no_match.group(1))
                    team_a, team_b = sorted(teams_found)
                    schedule_lookup[(match_no, frozenset({team_a, team_b}))] = int(match_id_match.group(1))
                    matched = True
                    break

                if not matched:
                    continue

            if schedule_lookup:
                return schedule_lookup
        except Exception as exc:
            print(f"[ESPN] Schedule lookup failed for {schedule_url}: {exc}")

    return None


def initialize_espn_match_map(matches_data: list[dict]) -> dict[int, int]:
    global ESPN_MATCH_ID_MAP

    mapping: dict[int, int] = {}
    missing_matches: list[dict] = []
    for match in matches_data:
        our_match_id = int(match["MatchID"])
        stored_match_id = match.get("ESPNMatchID")
        espn_match_id = int(stored_match_id) if stored_match_id not in (None, "") else None
        if espn_match_id:
            mapping[our_match_id] = espn_match_id
        else:
            missing_matches.append(match)

    ESPN_MATCH_ID_MAP.update(mapping)

    if missing_matches:
        schedule_lookup = _fetch_espn_schedule_lookup()
        if schedule_lookup:
            for match in missing_matches:
                our_match_id = int(match["MatchID"])
                key = _normalize_espn_match_key(our_match_id, match["Team1"], match["Team2"])
                espn_match_id = schedule_lookup.get(key)
                if not espn_match_id:
                    continue
                mapping[our_match_id] = espn_match_id
                ESPN_MATCH_ID_MAP[our_match_id] = espn_match_id
                try:
                    data_service.update_match_fields(our_match_id, espn_match_id=int(espn_match_id))
                except Exception:
                    pass

    print(f"[ESPN] Cached {len(ESPN_MATCH_ID_MAP)} match id mappings")
    return ESPN_MATCH_ID_MAP


def resolve_espn_match_id(match_id: int, team1: str, team2: str, force_refresh: bool = False) -> int | None:
    stored_match_id = None
    try:
        stored_match_id = data_service.get_stored_espn_match_id(int(match_id))
    except Exception:
        stored_match_id = None

    if stored_match_id and not force_refresh:
        ESPN_MATCH_ID_MAP[int(match_id)] = int(stored_match_id)
        return int(stored_match_id)

    cached_match_id = ESPN_MATCH_ID_MAP.get(int(match_id))
    if cached_match_id and not force_refresh:
        return int(cached_match_id)

    schedule_lookup = _fetch_espn_schedule_lookup()
    if not schedule_lookup:
        return int(stored_match_id) if stored_match_id else cached_match_id

    key = _normalize_espn_match_key(int(match_id), team1, team2)
    resolved = schedule_lookup.get(key)
    if resolved:
        ESPN_MATCH_ID_MAP[int(match_id)] = int(resolved)
        try:
            data_service.update_match_fields(int(match_id), espn_match_id=int(resolved))
        except Exception:
            pass
        return int(resolved)

    return int(stored_match_id) if stored_match_id else cached_match_id


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", value)


def _ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _expand_team_name(team_name: str) -> str:
    reverse_team_map = {
        short: full
        for full, short in TEAM_MAP.items()
        if len(short) <= 4 and full != short
    }
    return reverse_team_map.get(team_name, team_name)


def _to_short_team_name(team_name: str) -> str:
    return TEAM_MAP.get(team_name, team_name)


def build_ipl_playing_xi_url(match_id: int, team1: str, team2: str) -> str:
    espn_match_id = resolve_espn_match_id(int(match_id), team1, team2)
    if not espn_match_id:
        espn_match_id = int(match_id) + ESPN_MATCH_ID_OFFSET
    matchup_slug = f"{_slugify(_expand_team_name(team1))}-vs-{_slugify(_expand_team_name(team2))}"
    return (
        f"https://www.espncricinfo.com/series/{ESPN_IPL_SERIES_SLUG}-{ESPN_IPL_SERIES_ID}/"
        f"{matchup_slug}-{_ordinal(int(match_id))}-match-{espn_match_id}/match-playing-xi"
    )


def build_ipl_playing_xi_urls(match_id: int, team1: str, team2: str) -> list[str]:
    espn_match_id = resolve_espn_match_id(int(match_id), team1, team2)
    if not espn_match_id:
        espn_match_id = int(match_id) + ESPN_MATCH_ID_OFFSET
    team1_slug = _slugify(_expand_team_name(team1))
    team2_slug = _slugify(_expand_team_name(team2))
    matchup_slug = f"{team1_slug}-vs-{team2_slug}"

    candidates = [
        build_ipl_playing_xi_url(match_id, team1, team2),
        f"https://www.espncricinfo.com/series/{ESPN_IPL_SERIES_SLUG}-{ESPN_IPL_SERIES_ID}/{matchup_slug}-match-{espn_match_id}/match-playing-xi",
        f"https://www.espncricinfo.com/series/{ESPN_IPL_SERIES_SLUG}-{ESPN_IPL_SERIES_ID}/{matchup_slug}-{espn_match_id}/match-playing-xi",
        f"https://www.espncricinfo.com/series/{ESPN_IPL_SERIES_SLUG}-{ESPN_IPL_SERIES_ID}/{matchup_slug}-{_ordinal(int(match_id))}-match-{espn_match_id}/live-cricket-score",
        f"https://www.espncricinfo.com/series/{ESPN_IPL_SERIES_SLUG}-{ESPN_IPL_SERIES_ID}/{matchup_slug}-match-{espn_match_id}/live-cricket-score",
    ]

    unique_candidates: list[str] = []
    seen = set()
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique_candidates.append(candidate)

    return unique_candidates


def _normalize_player_name(name: str) -> str:
    name = re.sub(r"[\u2020\u2021*]", "", str(name))
    name = re.sub(r"\s*\((?:c|wk|sub)\)\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    return " ".join(name.split()).strip()


def _build_team_player_lookup(players_rows: list[dict]) -> dict[str, dict[str, int]]:
    lookup: dict[str, dict[str, int]] = {}

    for player in players_rows:
        team = player["team"]
        team_lookup = lookup.setdefault(team, {})
        names = [player["name"]]
        aliases = (player.get("aliases") or "").split(",")
        names.extend(alias.strip() for alias in aliases if alias.strip())

        for raw_name in names:
            normalized = _normalize_player_name(raw_name)
            if normalized:
                team_lookup[normalized] = player["id"]

    return lookup


def _extract_candidate_names_from_json(value, names: list[str]):
    if isinstance(value, dict):
        for key, item in value.items():
            key_normalized = str(key).lower()
            if key_normalized in {"name", "longname", "full_name", "fullname", "cardlongname"} and isinstance(item, str):
                names.append(item)
            else:
                _extract_candidate_names_from_json(item, names)
        return

    if isinstance(value, list):
        for item in value:
            _extract_candidate_names_from_json(item, names)


def _normalize_cricbuzz_match_key(match_id: int, team1: str, team2: str) -> tuple[int, frozenset[str]]:
    return (
        int(match_id),
        frozenset({_to_short_team_name(team1), _to_short_team_name(team2)}),
    )


def _fetch_and_store_cricbuzz_match_id(match_id: int, team1: str, team2: str) -> int | None:
    schedule_lookup = _fetch_cricbuzz_schedule_lookup()
    if not schedule_lookup:
        return None

    key = _normalize_cricbuzz_match_key(match_id, team1, team2)
    resolved = schedule_lookup.get(key)
    if resolved:
        CRICBUZZ_MATCH_ID_MAP[int(match_id)] = resolved
        try:
            data_service.update_match_fields(int(match_id), cricbuzz_match_id=int(resolved))
        except Exception:
            pass
    return resolved


def initialize_cricbuzz_match_map(matches_data: list[dict]) -> dict[int, int]:
    global CRICBUZZ_MATCH_ID_MAP

    mapping: dict[int, int] = {}
    missing_matches: list[dict] = []
    for match in matches_data:
        our_match_id = int(match["MatchID"])
        stored_match_id = match.get("CricbuzzMatchID")
        cricbuzz_match_id = int(stored_match_id) if stored_match_id not in (None, "") else None
        if cricbuzz_match_id:
            mapping[our_match_id] = cricbuzz_match_id
        else:
            missing_matches.append(match)

    CRICBUZZ_MATCH_ID_MAP.update(mapping)

    if missing_matches:
        schedule_lookup = _fetch_cricbuzz_schedule_lookup()
        if schedule_lookup:
            for match in missing_matches:
                our_match_id = int(match["MatchID"])
                key = _normalize_cricbuzz_match_key(our_match_id, match["Team1"], match["Team2"])
                cricbuzz_match_id = schedule_lookup.get(key)
                if not cricbuzz_match_id:
                    continue
                mapping[our_match_id] = cricbuzz_match_id
                CRICBUZZ_MATCH_ID_MAP[our_match_id] = cricbuzz_match_id
                try:
                    data_service.update_match_fields(our_match_id, cricbuzz_match_id=int(cricbuzz_match_id))
                except Exception:
                    pass

    print(f"[Cricbuzz] Cached {len(CRICBUZZ_MATCH_ID_MAP)} match id mappings")
    return CRICBUZZ_MATCH_ID_MAP


def _fetch_cricbuzz_schedule_lookup() -> dict[tuple[int, frozenset[str]], int] | None:
    schedule_url = build_cricbuzz_schedule_url()
    print(f"[Cricbuzz] Loading schedule mapping from {schedule_url}")

    try:
        res = _session_get(schedule_url)
        if res.status_code != 200:
            print(f"[Cricbuzz] Schedule fetch failed with status {res.status_code}")
            return None

        soup = BeautifulSoup(res.text, "html.parser")
        schedule_lookup: dict[tuple[int, frozenset[str]], int] = {}

        for anchor in soup.find_all("a", href=True, title=True):
            href = anchor.get("href", "")
            title = anchor.get("title", "")
            match_id_match = re.search(r"/live-cricket-scores/(\d+)", href)
            title_match = re.match(r"(.+?) vs (.+?), (\d+)(?:st|nd|rd|th) Match\b", title, flags=re.IGNORECASE)
            if not match_id_match or not title_match:
                continue

            team_a = _to_short_team_name(title_match.group(1).strip())
            team_b = _to_short_team_name(title_match.group(2).strip())
            match_no = int(title_match.group(3))
            cricbuzz_match_id = int(match_id_match.group(1))
            schedule_lookup[(match_no, frozenset({team_a, team_b}))] = cricbuzz_match_id

        # Completed and older matches are consistently present in the embedded
        # matchesData payload even when they are not rendered as title anchors.
        matches_data_payload = _extract_cricbuzz_embedded_json(res.text, "matchesData")
        if matches_data_payload:
            for section in matches_data_payload.get("matchDetails", []):
                match_map = section.get("matchDetailsMap", {})
                for match in match_map.get("match", []):
                    match_info = match.get("matchInfo", {})
                    match_desc = str(match_info.get("matchDesc", ""))
                    desc_match = re.match(r"(\d+)(?:st|nd|rd|th)? Match\b", match_desc, flags=re.IGNORECASE)
                    if not desc_match:
                        continue

                    cricbuzz_match_id = int(match_info.get("matchId"))
                    match_no = int(desc_match.group(1))
                    team_a = _to_short_team_name((match_info.get("team1") or {}).get("teamSName", "").strip())
                    team_b = _to_short_team_name((match_info.get("team2") or {}).get("teamSName", "").strip())
                    if team_a and team_b:
                        schedule_lookup[(match_no, frozenset({team_a, team_b}))] = cricbuzz_match_id

        return schedule_lookup
    except Exception as e:
        print(f"[Cricbuzz] Error loading schedule mapping: {e}")
        return None


def _extract_cricbuzz_embedded_json(html_text: str, key: str) -> dict | None:
    marker = f'{key}\\":{{'
    start = html_text.find(marker)
    if start == -1:
        return None

    index = start + len(marker) - 1
    brace_count = 0
    payload_chars = []
    started = False

    for ch in html_text[index:]:
        if ch == "{":
            brace_count += 1
            started = True
        if started:
            payload_chars.append(ch)
        if ch == "}":
            brace_count -= 1
            if started and brace_count == 0:
                break

    if not payload_chars:
        return None

    try:
        payload_text = "".join(payload_chars).encode("utf-8").decode("unicode_escape")
        return json.loads(payload_text)
    except Exception as exc:
        print(f"[Cricbuzz] Failed to parse embedded {key} payload: {exc}")
        return None


def resolve_cricbuzz_match_id(match_id: int, team1: str, team2: str, force_refresh: bool = False) -> int | None:
    stored_match_id = None
    try:
        stored_match_id = data_service.get_stored_cricbuzz_match_id(int(match_id))
    except Exception:
        stored_match_id = None

    if stored_match_id and not force_refresh:
        CRICBUZZ_MATCH_ID_MAP[int(match_id)] = stored_match_id
        return stored_match_id

    cached_match_id = CRICBUZZ_MATCH_ID_MAP.get(int(match_id))
    if cached_match_id and not force_refresh:
        return cached_match_id

    resolved = _fetch_and_store_cricbuzz_match_id(match_id, team1, team2)
    if resolved:
        CRICBUZZ_MATCH_ID_MAP[int(match_id)] = resolved
        return resolved

    if cached_match_id:
        return cached_match_id

    if stored_match_id:
        return stored_match_id

    return resolved


def _is_likely_player_name(name: str) -> bool:
    normalized = _normalize_player_name(name)
    if not normalized:
        return False
    parts = normalized.split()
    if len(parts) < 2 or len(parts) > 5:
        return False
    banned = {
        "playing xi", "squad", "impact subs", "impact players", "match details",
        "batting", "bowling", "fall of wickets", "toss", "live score", "scorecard",
    }
    return normalized not in banned


def _match_candidate_names(
    candidate_names: list[str],
    player_lookup: dict[str, dict[str, int]],
) -> tuple[set[int], list[str]]:
    playing_ids: set[int] = set()
    unmatched_names: list[str] = []
    seen_unmatched: set[str] = set()

    for raw_name in candidate_names:
        normalized = _normalize_player_name(raw_name)
        if not normalized:
            continue

        matched = False
        for team_lookup in player_lookup.values():
            player_id = team_lookup.get(normalized)
            if player_id:
                playing_ids.add(player_id)
                matched = True
                break

        if not matched and _is_likely_player_name(raw_name) and normalized not in seen_unmatched:
            seen_unmatched.add(normalized)
            unmatched_names.append(str(raw_name).strip())

    return playing_ids, unmatched_names


def _extract_team_names_from_column(column) -> list[str]:
    names: list[str] = []
    for row in column.find_all("a", href=True, recursive=False):
        spans = row.find_all("span")
        for span in spans:
            text = span.get_text(" ", strip=True)
            if not text or text.startswith("("):
                continue
            names.append(text)
            break
    return names


def _build_registry_from_players_rows(players_rows: list[dict]) -> PlayerRegistry:
    players_data = []
    for row in players_rows:
        players_data.append({
            "PlayerID": row["id"],
            "Name": row["name"],
            "Team": row["team"],
            "Role": row.get("role", ""),
            "Aliases": row.get("aliases") or "",
        })
    return PlayerRegistry(players_data)


def _find_registry_player_id_silent(registry: PlayerRegistry, raw_name: str, team: str) -> int | None:
    normalized_name = registry.normalize(raw_name)

    if (team, normalized_name) in registry.lookup:
        return registry.lookup[(team, normalized_name)]

    parts = normalized_name.split()
    if len(parts) > 1:
        first_name_matches = registry.first_name_lookup.get((team, parts[0]), set())
        last_name_matches = registry.last_name_lookup.get((team, parts[-1]), set())
        combined_matches = first_name_matches & last_name_matches
        if len(combined_matches) == 1:
            return next(iter(combined_matches))
    elif len(parts) == 1:
        first_name_matches = registry.first_name_lookup.get((team, parts[0]), set())
        if len(first_name_matches) == 1:
            return next(iter(first_name_matches))

        last_name_matches = registry.last_name_lookup.get((team, parts[0]), set())
        if len(last_name_matches) == 1:
            return next(iter(last_name_matches))

    initials, surname = registry._extract_initials_and_surname(normalized_name)
    if surname:
        surname_matches = registry.last_name_lookup.get((team, surname), set())
        if len(surname_matches) == 1:
            return next(iter(surname_matches))

        if initials:
            first_initial = initials[0]
            matching_candidates = []
            for pid in surname_matches:
                player_name = registry.normalize(registry.players.get(pid, {}).get("Name", ""))
                if not player_name:
                    continue
                player_parts = player_name.split()
                if player_parts and player_parts[0].startswith(first_initial):
                    matching_candidates.append(pid)

            if len(matching_candidates) == 1:
                return matching_candidates[0]

    return None


def _find_close_team_player_id(raw_name: str, team: str, players_rows: list[dict]) -> int | None:
    normalized_target = _normalize_player_name(raw_name)
    if not normalized_target:
        return None

    target_tokens = set(normalized_target.split())

    best_player_id = None
    best_score = 0.0
    tie = False

    for row in players_rows:
        if row["team"] != team:
            continue

        candidate_names = [row["name"]]
        aliases = (row.get("aliases") or "").split(",")
        candidate_names.extend(alias.strip() for alias in aliases if alias.strip())

        candidate_score = 0.0
        for candidate in candidate_names:
            normalized_candidate = _normalize_player_name(candidate)
            if not normalized_candidate:
                continue
            candidate_tokens = set(normalized_candidate.split())
            if target_tokens and target_tokens.issubset(candidate_tokens):
                candidate_score = max(candidate_score, 0.97)
                continue
            if normalized_target in normalized_candidate or normalized_candidate in normalized_target:
                candidate_score = max(candidate_score, 0.94)
                continue
            score = SequenceMatcher(None, normalized_target, normalized_candidate).ratio()
            candidate_score = max(candidate_score, score)

        if candidate_score > best_score:
            best_score = candidate_score
            best_player_id = row["id"]
            tie = False
        elif candidate_score == best_score and candidate_score > 0:
            tie = True

    if best_player_id and best_score >= 0.82 and not tie:
        return int(best_player_id)
    return None


def _resolve_team_player_ids_from_names(
    names: list[str],
    team: str,
    players_rows: list[dict],
) -> tuple[list[int], list[str]]:
    registry = _build_registry_from_players_rows(players_rows)
    ordered_ids: list[int] = []
    seen_ids: set[int] = set()
    unmatched_names: list[str] = []
    seen_unmatched: set[str] = set()

    for raw_name in names:
        cleaned_name = re.sub(
            r"\((?:w|wk|c|sub|w\s*/\s*c|c\s*/\s*w|wk\s*/\s*c|c\s*/\s*wk)\)",
            "",
            raw_name,
            flags=re.IGNORECASE,
        ).strip()
        normalized = _normalize_player_name(cleaned_name)
        if not normalized:
            continue

        player_id = _find_registry_player_id_silent(registry, cleaned_name, team)
        if not player_id:
            player_id = _find_close_team_player_id(cleaned_name, team, players_rows)

        if player_id:
            if player_id not in seen_ids:
                seen_ids.add(player_id)
                ordered_ids.append(player_id)
        elif normalized not in seen_unmatched:
            seen_unmatched.add(normalized)
            unmatched_names.append(cleaned_name)

    return ordered_ids, unmatched_names


def _extract_candidate_names(value: str) -> list[str]:
    parts = re.split(r"(?:,|;|\||•|·|\n|\r|\t)", value)
    return [name.strip() for name in parts if name.strip()]


def _extract_comma_separated_names(value: str) -> list[str]:
    return _extract_candidate_names(value)


def _team_name_variants(team_name: str) -> set[str]:
    variants = {_normalize_player_name(team_name), _normalize_player_name(_expand_team_name(team_name))}
    return {variant for variant in variants if variant}


def _resolve_toss_team(raw_team_text: str, team1: str, team2: str) -> str | None:
    normalized_raw = _normalize_player_name(raw_team_text)
    if normalized_raw in _team_name_variants(team1):
        return team1
    if normalized_raw in _team_name_variants(team2):
        return team2
    return None


def _extract_toss_info_from_html(html: str, team1: str, team2: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    if not text:
        return None

    patterns = [
        r"([A-Za-z .-]+?)\s+have won the toss and have opted to\s+(bat|bowl)",
        r"([A-Za-z .-]+?)\s+won the toss and opted to\s+(bat|bowl)",
        r"([A-Za-z .-]+?)\s+opt to\s+(bat|bowl)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        resolved_team = _resolve_toss_team(match.group(1).strip(), team1, team2)
        if not resolved_team:
            continue
        decision = match.group(2).lower()
        return {
            "announced": True,
            "team": resolved_team,
            "decision": decision,
            "text": f"{resolved_team} opt to {decision}",
        }

    return None


def extract_match_completion_status_from_cricbuzz_html(
    html: str,
    team1: str | None = None,
    team2: str | None = None,
) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text("\n", strip=True)
    if not page_text:
        return None

    current_match_excerpt = _extract_current_match_excerpt(page_text, team1, team2)
    relevant_text = current_match_excerpt or page_text

    candidate_team_names = [team1, team2]
    for team_name in candidate_team_names:
        if not team_name:
            continue
        for variant in {team_name, _expand_team_name(team_name)}:
            if not variant:
                continue
            match = re.search(
                rf"({re.escape(variant)}\s+won\s+by\s+[^.\n]+)",
                relevant_text,
                flags=re.IGNORECASE,
            )
            if match:
                return {
                    "status": "completed",
                    "text": " ".join(match.group(1).split()),
                }

    generic_match = re.search(
        r"([A-Za-z][A-Za-z .-]+?\s+won\s+by\s+[^.\n]+)",
        relevant_text,
        flags=re.IGNORECASE,
    )
    if generic_match:
        return {
            "status": "completed",
            "text": " ".join(generic_match.group(1).split()),
        }
    return None


def _extract_current_match_excerpt(page_text: str, team1: str | None = None, team2: str | None = None) -> str:
    if not team1 and not team2:
        return page_text

    candidate_positions: list[int] = []
    if team1 and team2:
        team1_variants = {team1, _expand_team_name(team1)}
        team2_variants = {team2, _expand_team_name(team2)}
        for variant1 in team1_variants:
            for variant2 in team2_variants:
                if not variant1 or not variant2:
                    continue
                for matchup in (f"{variant1} vs {variant2}", f"{variant2} vs {variant1}"):
                    search_start = 0
                    while True:
                        pos = page_text.lower().find(matchup.lower(), search_start)
                        if pos < 0:
                            break
                        candidate_positions.append(pos)
                        search_start = pos + 1

    name_variants: list[str] = []
    for team_name in [team1, team2]:
        if not team_name:
            continue
        for variant in {team_name, _expand_team_name(team_name)}:
            if variant:
                name_variants.append(variant)

    if not candidate_positions:
        for variant in name_variants:
            search_start = 0
            while True:
                pos = page_text.lower().find(variant.lower(), search_start)
                if pos < 0:
                    break
                candidate_positions.append(pos)
                search_start = pos + 1

    if not candidate_positions:
        return ""

    best_excerpt = ""
    best_score = float("-inf")
    score_markers = [
        (r"\bwon\s+by\b", 12),
        (r"\bno result\b", 10),
        (r"\bmatch abandoned\b", 10),
        (r"\binnings break\b", 8),
        (r"\bneed\s+\d+\s+runs?\b", 8),
        (r"\bopt\s+to\b", 6),
        (r"\bvenue\b", 4),
        (r"\bdate\s*&\s*time\b", 4),
        (r"\binfo\b", 3),
        (r"\bscorecard\b", 3),
    ]

    for start in candidate_positions:
        excerpt = page_text[start:min(start + 2200, len(page_text))]
        score = start / 1000.0
        for pattern, weight in score_markers:
            if re.search(pattern, excerpt, flags=re.IGNORECASE):
                score += weight
        if score > best_score:
            best_score = score
            best_excerpt = excerpt

    return best_excerpt


def _extract_playing_xi_from_commentary(
    html: str,
    team1: str,
    team2: str,
    players_rows: list[dict],
) -> tuple[list[int], list[int], list[str], list[str], bool]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text("\n", strip=True)
    if not page_text:
        return [], [], [], [], False
    page_lines = [line.strip() for line in page_text.splitlines() if line.strip()]

    expanded_team_names = {
        team1: {team1, _expand_team_name(team1)},
        team2: {team2, _expand_team_name(team2)},
    }

    playing_ids: list[int] = []
    substitute_ids: list[int] = []
    unmatched_playing: list[str] = []
    unmatched_substitutes: list[str] = []
    normalized_page_text = " ".join(page_text.split())

    def _extract_names_from_line(line: str, team: str) -> tuple[list[str], list[str]]:
        """Parse a single commentary line for team-specific XI/substitute names."""
        team_variants = expanded_team_names[team]
        for variant in team_variants:
            if not variant:
                continue

            xi_match = re.search(
                rf"(?:^|\bTeams:\s*){re.escape(variant)}\s*\(Playing XI\)\s*[:\-]\s*(.+)$",
                line,
                flags=re.IGNORECASE,
            )
            if xi_match:
                return _extract_comma_separated_names(xi_match.group(1)), []

            subs_match = re.search(
                rf"(?:^|\bTeams:\s*){re.escape(variant)}\s+Impact\s+(?:sub|subs|substitute|substitutes)\s*[:\-]\s*(.+)$",
                line,
                flags=re.IGNORECASE,
            )
            if subs_match:
                return [], _extract_comma_separated_names(subs_match.group(1))

        return [], []

    def _line_is_section_heading(line: str, team: str, section: str) -> bool:
        team_variants = expanded_team_names[team]
        for variant in team_variants:
            if not variant:
                continue
            if re.search(
                rf"(?:^|\bTeams:\s*){re.escape(variant)}\s*\({re.escape(section)}\)\s*[:\-]?\s*$",
                line,
                flags=re.IGNORECASE,
            ):
                return True
        return False

    def _is_any_team_marker(line: str) -> bool:
        normalized_line = _normalize_player_name(line)
        if not normalized_line:
            return False
        markers = {
            _normalize_player_name(team1),
            _normalize_player_name(team2),
            _normalize_player_name(_expand_team_name(team1)),
            _normalize_player_name(_expand_team_name(team2)),
            _normalize_player_name("Teams"),
            _normalize_player_name("Playing XI"),
            _normalize_player_name("Impact subs"),
            _normalize_player_name("Impact substitutes"),
        }
        return normalized_line in markers

    def _collect_section_names(team: str, start_index: int, section: str, initial_names: list[str]) -> list[str]:
        collected_names = list(initial_names)
        other_team_markers = expanded_team_names[team1 if team == team2 else team2]
        current_team_markers = expanded_team_names[team]
        max_rows = 18 if section == "playing xi" else 10

        for tail_line in page_lines[start_index + 1:start_index + 24]:
            normalized_tail = _normalize_player_name(tail_line)
            if not normalized_tail:
                continue
            tail_lower = tail_line.lower()
            other_team_hit = any(marker.lower() in tail_lower for marker in other_team_markers if marker)
            current_team_hit = any(marker.lower() in tail_lower for marker in current_team_markers if marker)
            if other_team_hit and not current_team_hit and collected_names:
                break
            if _is_any_team_marker(tail_line):
                if collected_names:
                    break
                continue
            if other_team_hit and not current_team_hit:
                break
            if "playing xi" in normalized_tail and section != "playing xi":
                break
            if "impact sub" in normalized_tail and section == "playing xi" and collected_names:
                break
            collected_names.extend(_extract_candidate_names(tail_line))
            if len(collected_names) >= max_rows:
                break

        return collected_names

    def _extract_from_lines(team: str) -> tuple[list[str], list[str]]:
        xi_names: list[str] = []
        substitute_names: list[str] = []

        for index, line in enumerate(page_lines):
            line_xi, line_subs = _extract_names_from_line(line, team)
            if line_xi:
                collected_xi = _collect_section_names(team, index, "playing xi", line_xi)
                for name in collected_xi:
                    if name not in xi_names:
                        xi_names.append(name)
            if line_subs:
                collected_subs = _collect_section_names(team, index, "impact subs", line_subs)
                for name in collected_subs:
                    if name not in substitute_names:
                        substitute_names.append(name)

            if _line_is_section_heading(line, team, "Playing XI") and not line_xi:
                collected_xi = _collect_section_names(team, index, "playing xi", [])
                for name in collected_xi:
                    if name not in xi_names:
                        xi_names.append(name)
            if (
                _line_is_section_heading(line, team, "Impact subs")
                or _line_is_section_heading(line, team, "Impact substitutes")
            ) and not line_subs:
                collected_subs = _collect_section_names(team, index, "impact subs", [])
                for name in collected_subs:
                    if name not in substitute_names:
                        substitute_names.append(name)

        return xi_names, substitute_names

    def _extract_block_names(section_label: str, team: str, name_variants: set[str]) -> list[str]:
        patterns = [
            rf"{re.escape(team)}\s+{re.escape(section_label)}\s*[:\-]\s*(.+?)(?=(?:{re.escape(team1)}|{re.escape(team2)}|Here are the|$))",
            rf"{re.escape(_expand_team_name(team))}\s+{re.escape(section_label)}\s*[:\-]\s*(.+?)(?=(?:{re.escape(team1)}|{re.escape(team2)}|Here are the|$))",
        ]
        for variant in name_variants:
            if not variant:
                continue
            patterns.extend([
                rf"{re.escape(variant)}\s+{re.escape(section_label)}\s*[:\-]\s*(.+?)(?=(?:{re.escape(team1)}|{re.escape(team2)}|Here are the|$))",
                rf"{re.escape(variant)}\s*[:\-]\s*(.+?)(?=(?:{re.escape(team1)}|{re.escape(team2)}|Here are the|$))",
            ])

        for pattern in patterns:
            match = re.search(pattern, normalized_page_text, flags=re.IGNORECASE)
            if match:
                raw_text = match.group(1).strip()
                names = _extract_comma_separated_names(raw_text.split("\n", 1)[0])
                if names:
                    return names
        return []

    def _extract_general_block_after_heading(heading_text: str, team: str) -> list[str]:
        heading_match = re.search(re.escape(heading_text), normalized_page_text, flags=re.IGNORECASE)
        if not heading_match:
            return []
        start = heading_match.end()
        tail = normalized_page_text[start:]
        team_markers = [team1, team2, _expand_team_name(team1), _expand_team_name(team2)]
        stop_pos = len(tail)
        for marker in team_markers:
            if not marker:
                continue
            marker_pos = tail.lower().find(marker.lower())
            if marker_pos >= 0:
                stop_pos = min(stop_pos, marker_pos)
        block = tail[:stop_pos].strip(" :.-\n")
        if not block:
            return []
        return _extract_comma_separated_names(block.split("\n", 1)[0])

    for team, name_variants in expanded_team_names.items():
        xi_names: list[str] = []
        substitute_names: list[str] = []

        if not xi_names or not substitute_names:
            line_xi_names, line_substitute_names = _extract_from_lines(team)
            if line_xi_names and not xi_names:
                xi_names = line_xi_names
            if line_substitute_names and not substitute_names:
                substitute_names = line_substitute_names

        for variant in name_variants:
            escaped_variant = re.escape(variant)
            xi_match = re.search(
                rf"{escaped_variant}\s*\(Playing XI\)\s*[:\-]\s*(.+)",
                page_text,
                flags=re.IGNORECASE,
            )
            if xi_match and not xi_names:
                xi_names = _extract_comma_separated_names(xi_match.group(1).split("\n", 1)[0])

            subs_match = re.search(
                rf"{escaped_variant}\s+Impact\s+(?:sub|subs|substitute|substitutes)\s*[:\-]\s*(.+)",
                page_text,
                flags=re.IGNORECASE,
            )
            if subs_match and not substitute_names:
                substitute_names = _extract_comma_separated_names(subs_match.group(1).split("\n", 1)[0])

        if not substitute_names:
            substitute_names = _extract_block_names("Impact substitutes", team, name_variants)
        if not substitute_names:
            substitute_names = _extract_general_block_after_heading("Here are the Impact substitutes for both the teams", team)
        if not xi_names:
            xi_names = _extract_block_names("Playing XI", team, name_variants)
        if not xi_names:
            xi_names = _extract_general_block_after_heading("Here are the Playing XI for both the teams", team)

        if xi_names:
            resolved_ids, unresolved_names = _resolve_team_player_ids_from_names(xi_names, team, players_rows)
            playing_ids.extend(resolved_ids)
            unmatched_playing.extend(unresolved_names)
        if substitute_names:
            resolved_ids, unresolved_names = _resolve_team_player_ids_from_names(substitute_names, team, players_rows)
            substitute_ids.extend(resolved_ids)
            unmatched_substitutes.extend(unresolved_names)

    announced = len(playing_ids) == 22
    return playing_ids, substitute_ids, unmatched_playing, unmatched_substitutes, announced


def parse_playing_xi_from_sources(
    commentary_html: str | None,
    squads_html: str | None,
    team1: str,
    team2: str,
    players_rows: list[dict],
    commentary_url: str = "",
    squads_url: str = "",
) -> dict:
    payload = {
        "announced": False,
        "url": "",
        "player_ids": [],
        "substitute_ids": [],
        "unmatched_names": [],
        "substitute_unmatched_names": [],
        "source": "",
        "substitutes_available": False,
        "finalized": False,
    }

    if commentary_html:
        (
            playing_ids,
            substitute_ids,
            unmatched_names,
            substitute_unmatched_names,
            announced,
        ) = _extract_playing_xi_from_commentary(commentary_html, team1, team2, players_rows)
        if len(playing_ids) == 22:
            payload.update(
                {
                    "announced": True,
                    "url": commentary_url or "commentary",
                    "player_ids": list(playing_ids),
                    "substitute_ids": list(substitute_ids),
                    "unmatched_names": list(unmatched_names),
                    "substitute_unmatched_names": list(substitute_unmatched_names),
                    "source": "commentary",
                    "substitutes_available": len(substitute_ids) > 0,
                }
            )

    if not payload["announced"] and squads_html:
        playing_ids, unmatched_names, announced = _extract_named_players_from_cricbuzz_section(
            squads_html, "playing xi", team1, team2, players_rows
        )
        substitute_ids, substitute_unmatched_names, substitutes_available = _extract_named_players_from_cricbuzz_section(
            squads_html, "substitutes", team1, team2, players_rows
        )
        if len(playing_ids) < 18:
            payload_playing_ids, payload_unmatched_playing, payload_substitute_ids, payload_unmatched_substitutes = _extract_playing_xi_from_squads_payload(
                squads_html, players_rows
            )
            if len(payload_playing_ids) > len(playing_ids):
                playing_ids = payload_playing_ids
                unmatched_names = payload_unmatched_playing
                announced = len(playing_ids) >= 18
            if len(payload_substitute_ids) > len(substitute_ids):
                substitute_ids = payload_substitute_ids
                substitute_unmatched_names = payload_unmatched_substitutes
                substitutes_available = len(substitute_ids) > 0
        # Cricbuzz has multiple squads page layouts; if the structured column parser
        # doesn't see enough names, fall back to the more permissive text parser.
        if len(playing_ids) < 18:
            text_playing_ids, text_unmatched_names = _extract_playing_xi_from_text(
                squads_html, team1, team2, players_rows
            )
            if len(text_playing_ids) > len(playing_ids):
                playing_ids = list(text_playing_ids)
                unmatched_names = text_unmatched_names
                announced = len(playing_ids) >= 18
        if len(playing_ids) < 22:
            json_playing_ids, json_unmatched_names = _extract_playing_xi_from_json(squads_html, players_rows)
            if len(json_playing_ids) == 22 and len(json_playing_ids) > len(playing_ids):
                playing_ids = list(json_playing_ids)
                unmatched_names = json_unmatched_names
                announced = True
        if len(playing_ids) == 22:
            payload.update(
                {
                    "announced": True,
                    "url": squads_url or "squads",
                    "player_ids": list(playing_ids),
                    "substitute_ids": list(substitute_ids),
                    "unmatched_names": list(unmatched_names),
                    "substitute_unmatched_names": list(substitute_unmatched_names),
                    "source": "squads",
                    "substitutes_available": bool(substitutes_available),
                }
            )

    payload["announced"] = _is_playing_xi_announced(payload)
    payload["finalized"] = _is_finalized_playing_xi(payload)
    if len(payload["substitute_ids"]) > 10:
        print(
            f"[Playing XI] source={payload.get('source') or 'unknown'} "
            f"produced {len(payload['substitute_ids'])} substitute candidates; capping to 10"
        )
        payload["substitute_ids"] = payload["substitute_ids"][:10]
    return payload


def _find_cricbuzz_section_heading(soup: BeautifulSoup, section_name: str):
    target = _normalize_player_name(section_name)
    for tag in soup.find_all(["h1", "h2", "h3"]):
        if _normalize_player_name(tag.get_text(" ", strip=True)) == target:
            return tag
    return None


def _extract_named_players_from_cricbuzz_section(
    html: str,
    section_name: str,
    team1: str,
    team2: str,
    players_rows: list[dict],
) -> tuple[list[int], list[str], bool]:
    soup = BeautifulSoup(html, "html.parser")
    heading = _find_cricbuzz_section_heading(soup, section_name)

    if not heading:
        return set(), [], False

    container = heading.find_next(
        lambda tag: (
            tag.name == "div"
            and len([
                child for child in tag.find_all("div", recursive=False)
                if "w-1/2" in " ".join(child.get("class", []))
            ]) >= 2
        )
    )
    if not container:
        return set(), [], True

    columns = [
        child for child in container.find_all("div", recursive=False)
        if "w-1/2" in " ".join(child.get("class", []))
    ][:2]
    if len(columns) < 2:
        return set(), [], True

    registry = _build_registry_from_players_rows(players_rows)
    ordered_ids: list[int] = []
    seen_ids: set[int] = set()
    unmatched_names: list[str] = []
    seen_unmatched: set[str] = set()

    for team, column in zip((team1, team2), columns):
        for raw_name in _extract_team_names_from_column(column):
            normalized = _normalize_player_name(raw_name)
            if not normalized:
                continue
            player_id = _find_registry_player_id_silent(registry, raw_name, team)
            if not player_id:
                player_id = _find_close_team_player_id(raw_name, team, players_rows)
            if player_id:
                if player_id not in seen_ids:
                    seen_ids.add(player_id)
                    ordered_ids.append(player_id)
            elif normalized not in seen_unmatched:
                seen_unmatched.add(normalized)
                unmatched_names.append(raw_name)

    return ordered_ids, unmatched_names, True


def _extract_playing_xi_from_json(html: str, players_rows: list[dict]) -> tuple[set[int], list[str]]:
    player_lookup = _build_team_player_lookup(players_rows)
    all_names: list[str] = []

    script_matches = re.findall(
        r'<script[^>]*type="application/json"[^>]*>(.*?)</script>|<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    for match in script_matches:
        script_content = next((part for part in match if part), "")
        if not script_content:
            continue

        try:
            data = json.loads(script_content)
        except Exception:
            continue

        _extract_candidate_names_from_json(data, all_names)

    return _match_candidate_names(all_names, player_lookup)


def _extract_escaped_json_arrays(html: str, marker: str) -> list[str]:
    """Extract escaped JSON arrays from Next.js payloads."""
    arrays: list[str] = []
    search_start = 0

    while True:
        marker_pos = html.find(marker, search_start)
        if marker_pos == -1:
            break

        array_start = html.find("[", marker_pos)
        if array_start == -1:
            break

        depth = 0
        array_end = -1
        for idx in range(array_start, len(html)):
            ch = html[idx]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    array_end = idx
                    break

        if array_end == -1:
            break

        arrays.append(html[array_start:array_end + 1])
        search_start = array_end + 1

    return arrays


def _extract_playing_xi_from_squads_payload(html: str, players_rows: list[dict]) -> tuple[list[int], list[str], list[int], list[str]]:
    """Parse Cricbuzz squads payload arrays embedded in the page source."""
    team_lookup = _build_team_player_lookup(players_rows)
    playing_ids: list[int] = []
    substitute_ids: list[int] = []
    unmatched_playing: list[str] = []
    unmatched_substitutes: list[str] = []
    seen_playing: set[int] = set()
    seen_substitute: set[int] = set()

    def _team_for_name(team_name: str) -> str:
        normalized_team = _normalize_player_name(team_name)
        for team in team_lookup.keys():
            if _normalize_player_name(team) == normalized_team:
                return team
        return team_name

    def _consume_players(raw_array: str, substitute_flag: bool):
        nonlocal playing_ids, substitute_ids, unmatched_playing, unmatched_substitutes
        try:
            decoded = raw_array.encode("utf-8").decode("unicode_escape")
            players = json.loads(decoded)
        except Exception:
            return

        if not isinstance(players, list):
            return

        for player in players:
            if not isinstance(player, dict):
                continue

            name = str(player.get("name") or player.get("fullName") or "").strip()
            team_name = str(player.get("teamName") or "").strip()
            if not name or not team_name:
                continue

            team = _team_for_name(team_name)
            normalized_name = _normalize_player_name(name)
            player_id = team_lookup.get(team, {}).get(normalized_name)
            if not player_id:
                player_id = _find_close_team_player_id(name, team, players_rows)

            if player_id:
                if substitute_flag or bool(player.get("substitute")):
                    if player_id not in seen_substitute:
                        seen_substitute.add(player_id)
                        substitute_ids.append(player_id)
                else:
                    if player_id not in seen_playing:
                        seen_playing.add(player_id)
                        playing_ids.append(player_id)
            elif substitute_flag or bool(player.get("substitute")):
                unmatched_substitutes.append(name)
            else:
                unmatched_playing.append(name)

    for raw_array in _extract_escaped_json_arrays(html, '\\"playing XI\\":['):
        _consume_players(raw_array, substitute_flag=False)
    for raw_array in _extract_escaped_json_arrays(html, '\\"bench\\":['):
        _consume_players(raw_array, substitute_flag=True)

    return playing_ids, unmatched_playing, substitute_ids, unmatched_substitutes


def _extract_playing_xi_from_text(html: str, team1: str, team2: str, players_rows: list[dict]) -> tuple[set[int], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    player_lookup = _build_team_player_lookup(players_rows)
    playing_ids: set[int] = set()
    unmatched_names: list[str] = []
    unmatched_seen: set[str] = set()

    expanded_team_names = {
        team1: {_normalize_player_name(team1), _normalize_player_name(_expand_team_name(team1))},
        team2: {_normalize_player_name(team2), _normalize_player_name(_expand_team_name(team2))},
    }

    def gather_from_section(team: str, start_idx: int) -> tuple[set[int], list[str]]:
        ids: set[int] = set()
        unmatched: list[str] = []
        next_team_markers = expanded_team_names[team1 if team == team2 else team2]

        for line in lines[start_idx + 1:start_idx + 40]:
            normalized_line = _normalize_player_name(line)
            if not normalized_line:
                continue
            if normalized_line in next_team_markers and ids:
                break

            segments = re.split(r",|;|\u2022|\||\s{2,}", line)
            if len(segments) == 1:
                segments = [line]

            for segment in segments:
                segment = segment.strip()
                normalized_segment = _normalize_player_name(segment)
                if not normalized_segment:
                    continue

                player_id = player_lookup.get(team, {}).get(normalized_segment)
                if player_id:
                    ids.add(player_id)
                    if len(ids) >= 11:
                        break
                elif _is_likely_player_name(segment):
                    unmatched.append(segment)

            if len(ids) >= 11:
                break

        return ids, unmatched

    for team in (team1, team2):
        for idx, line in enumerate(lines):
            normalized_line = _normalize_player_name(line)
            if normalized_line in expanded_team_names[team]:
                section_ids, section_unmatched = gather_from_section(team, idx)
                if len(section_ids) >= 9:
                    playing_ids.update(section_ids)
                    for name in section_unmatched:
                        normalized_name = _normalize_player_name(name)
                        if normalized_name and normalized_name not in unmatched_seen:
                            unmatched_seen.add(normalized_name)
                            unmatched_names.append(name)
                    break

    return playing_ids, unmatched_names


def _fetch_playing_xi_impl(
    match_id: int,
    team1: str,
    team2: str,
    players_rows: list[dict],
    match_date: str | None = None,
    match_time: str | None = None,
    toss_time: str | None = None,
    force_refresh: bool = False,
) -> dict:
    with PLAYING_XI_CACHE_LOCK:
        cached = PLAYING_XI_CACHE.get(int(match_id))
    now_ts = time.time()
    allow_cache_read = not _is_before_match_start(match_date, match_time)
    print(
        f"[Playing XI] Match {match_id}: refresh requested "
        f"date={match_date or '<unknown>'} time={match_time or '<unknown>'} "
        f"toss={toss_time or '<unknown>'} force_refresh={force_refresh} "
        f"allow_cache_read={allow_cache_read} cached={'yes' if cached else 'no'}"
    )
    if not toss_time:
        try:
            match_row = data_service.get_match_by_id(int(match_id))
            toss_time = toss_time or (match_row or {}).get("toss_time")
        except Exception:
            toss_time = toss_time or None
    if cached:
        payload = _copy_playing_xi_payload(cached["payload"])
        if cached.get("finalized"):
            print(
                f"[Playing XI] Match {match_id}: returning finalized cache "
                f"url={payload.get('url') or '<unknown>'} players={len(payload.get('player_ids', []))} "
                f"subs={len(payload.get('substitute_ids', []))}"
            )
            try:
                data_service.set_cached_match_playing_xi(
                    match_id, team1, team2, match_date or "", match_time or "", payload
                )
            except Exception:
                pass
            return payload
        # Keep retrying until both the XI and substitutes are complete.
        # A 22-player announcement should update the UI, but it should not stop
        # us from checking for the 10 subs yet.
        if not force_refresh and allow_cache_read and now_ts - cached.get("fetched_at", 0) < PLAYING_XI_TTL_SECONDS:
            print(
                f"[Playing XI] Match {match_id}: cached data incomplete "
                f"(players={len(payload.get('player_ids', []))}, subs={len(payload.get('substitute_ids', []))}); refetching"
            )

    if not _should_attempt_playing_xi_fetch(match_date, match_time, toss_time):
        payload = {"announced": False, "url": "", "player_ids": [], "substitute_ids": []}
        try:
            data_service.set_cached_match_playing_xi(
                match_id, team1, team2, match_date or "", match_time or "", payload
            )
        except Exception:
            pass
        return payload

    cricbuzz_match_id = data_service.get_stored_cricbuzz_match_id(int(match_id)) or resolve_cricbuzz_match_id(int(match_id), team1, team2)
    if not cricbuzz_match_id:
        print(f"[Playing XI] Match {match_id}: no Cricbuzz match id found after schedule lookup")
        payload = {"announced": False, "url": "", "player_ids": [], "substitute_ids": []}
        try:
            data_service.set_cached_match_playing_xi(
                match_id, team1, team2, match_date or "", match_time or "", payload
            )
        except Exception:
            pass
        return payload

    commentary_url = build_cricbuzz_commentary_url(cricbuzz_match_id)
    squads_url = build_cricbuzz_playing_xi_url(cricbuzz_match_id)
    print(
        f"[Playing XI] Match {match_id}: resolved cricbuzz_match_id={cricbuzz_match_id} "
        f"squads_url={squads_url} commentary_url={commentary_url}"
    )

    try:
        squads_html = None
        print(f"[Playing XI] Match {match_id}: trying {squads_url}")
        res = _session_get(squads_url)
        if res.status_code == 200:
            squads_html = res.text
        elif team1 and team2:
            refreshed_match_id = resolve_cricbuzz_match_id(int(match_id), team1, team2, force_refresh=True)
            if refreshed_match_id and refreshed_match_id != cricbuzz_match_id:
                cricbuzz_match_id = refreshed_match_id
                commentary_url = build_cricbuzz_commentary_url(cricbuzz_match_id)
                squads_url = build_cricbuzz_playing_xi_url(cricbuzz_match_id)
                res = _session_get(squads_url)
                if res.status_code == 200:
                    squads_html = res.text

        parsed_from_squads = None
        if squads_html:
            parsed_from_squads = parse_playing_xi_from_sources(
                None,
                squads_html,
                team1,
                team2,
                players_rows,
                commentary_url=commentary_url,
                squads_url=squads_url,
            )

        commentary_html = None
        if not parsed_from_squads or not parsed_from_squads["finalized"]:
            print(f"[Playing XI] Match {match_id}: trying commentary {commentary_url}")
            commentary_res = _session_get(commentary_url)
            if commentary_res.status_code == 200:
                commentary_html = commentary_res.text
            elif team1 and team2:
                refreshed_match_id = resolve_cricbuzz_match_id(int(match_id), team1, team2, force_refresh=True)
                if refreshed_match_id and refreshed_match_id != cricbuzz_match_id:
                    cricbuzz_match_id = refreshed_match_id
                    commentary_url = build_cricbuzz_commentary_url(cricbuzz_match_id)
                    squads_url = build_cricbuzz_playing_xi_url(cricbuzz_match_id)
                    commentary_res = _session_get(commentary_url)
                    if commentary_res.status_code == 200:
                        commentary_html = commentary_res.text

        if not squads_html and not commentary_html:
            print(f"[Playing XI] Match {match_id}: unable to fetch squads/commentary")
            payload = {"announced": False, "url": squads_url, "player_ids": [], "substitute_ids": []}
            with PLAYING_XI_CACHE_LOCK:
                PLAYING_XI_CACHE[int(match_id)] = {
                    "payload": payload,
                    "fetched_at": now_ts,
                    "finalized": False,
                }
            try:
                data_service.set_cached_match_playing_xi(
                    match_id, team1, team2, match_date or "", match_time or "", payload
                )
            except Exception:
                pass
            return _copy_playing_xi_payload(payload)

        parsed_from_commentary = None
        if commentary_html:
            parsed_from_commentary = parse_playing_xi_from_sources(
                commentary_html,
                None,
                team1,
                team2,
                players_rows,
                commentary_url=commentary_url,
            )

        parsed_payload = _merge_playing_xi_payloads(parsed_from_squads, parsed_from_commentary)

        if len(parsed_payload["player_ids"]) < 22 or len(parsed_payload["substitute_ids"]) < 10:
            parsed_payload = parse_playing_xi_from_sources(
                commentary_html,
                squads_html,
                team1,
                team2,
                players_rows,
                commentary_url=commentary_url,
                squads_url=squads_url,
            )

        if not parsed_payload["announced"]:
            print(f"[Playing XI] Match {match_id}: Playing XI section not available yet")
            payload = {"announced": False, "url": parsed_payload.get("url", commentary_url), "player_ids": [], "substitute_ids": []}
            with PLAYING_XI_CACHE_LOCK:
                PLAYING_XI_CACHE[int(match_id)] = {
                    "payload": payload,
                    "fetched_at": now_ts,
                    "finalized": False,
                }
            try:
                data_service.set_cached_match_playing_xi(
                    match_id, team1, team2, match_date or "", match_time or "", payload
                )
            except Exception:
                pass
            return _copy_playing_xi_payload(payload)

        source_url = parsed_payload["url"] or commentary_url
        playing_ids = parsed_payload["player_ids"]
        substitute_ids = parsed_payload["substitute_ids"]
        winning_source = parsed_payload.get("source") or ("commentary" if parsed_from_commentary and parsed_from_commentary.get("source") == "commentary" else "squads" if parsed_from_squads else "unknown")
        print(
            f"[Playing XI] Match {match_id}: final source={winning_source} "
            f"url={source_url} playing={len(playing_ids)} subs={len(substitute_ids)} "
            f"finalized={parsed_payload.get('finalized', False)}"
        )
        if parsed_payload["announced"]:
            player_source = parsed_payload.get("source") or winning_source
            print(
                f"[Playing XI] Match {match_id}: Playing XI announced from {player_source} "
                f"({len(playing_ids)} players)"
            )
        if parsed_payload["substitutes_available"]:
            substitute_source = parsed_payload.get("source") or winning_source
            print(
                f"[Playing XI] Match {match_id}: substitutes announced from {substitute_source} "
                f"({len(substitute_ids)} players)"
            )
        for name in parsed_payload["unmatched_names"]:
            print(f"[Playing XI] Match {match_id}: player mapping not found for '{name}'")
        if parsed_payload["substitutes_available"]:
            print(f"[Playing XI] Match {match_id}: substitutes found ({len(substitute_ids)})")
            for name in parsed_payload["substitute_unmatched_names"]:
                print(f"[Playing XI] Match {match_id}: substitute mapping not found for '{name}'")

        payload = {
            "announced": parsed_payload["announced"],
            "url": source_url,
            "player_ids": list(playing_ids),
            "substitute_ids": list(substitute_ids),
        }
        with PLAYING_XI_CACHE_LOCK:
            PLAYING_XI_CACHE[int(match_id)] = {
                "payload": payload,
                "fetched_at": now_ts,
                "finalized": parsed_payload["finalized"],
            }
        try:
            data_service.set_cached_match_playing_xi(
                match_id, team1, team2, match_date or "", match_time or "", payload
            )
        except Exception:
            pass
        return _copy_playing_xi_payload(payload)
    except Exception as e:
        print("Error fetching playing XI:", e)
        payload = {"announced": False, "url": commentary_url, "player_ids": [], "substitute_ids": []}
        with PLAYING_XI_CACHE_LOCK:
            PLAYING_XI_CACHE[int(match_id)] = {
                "payload": payload,
                "fetched_at": now_ts,
                "finalized": False,
            }
        try:
            data_service.set_cached_match_playing_xi(
                match_id, team1, team2, match_date or "", match_time or "", payload
            )
        except Exception:
            pass
        return _copy_playing_xi_payload(payload)


def fetch_playing_xi(
    match_id: int,
    team1: str,
    team2: str,
    players_rows: list[dict],
    match_date: str | None = None,
    match_time: str | None = None,
    toss_time: str | None = None,
    force_refresh: bool = False,
) -> dict:
    # UI/API callers should only read the current cache snapshot.
    # Scheduler/admin code should call refresh_playing_xi_cache() instead.
    with PLAYING_XI_CACHE_LOCK:
        cached = PLAYING_XI_CACHE.get(int(match_id))
    if cached:
        return _copy_playing_xi_payload(cached["payload"])

    persisted = data_service.get_cached_match_playing_xi(
        match_id,
        team1,
        team2,
        match_date or "",
        match_time or "",
    )
    if persisted:
        return _copy_playing_xi_payload(persisted)

    return {"announced": False, "url": "", "player_ids": [], "substitute_ids": []}


def fetch_toss_info(
    match_id: int,
    team1: str,
    team2: str,
    match_date: str | None = None,
    match_time: str | None = None,
    toss_time: str | None = None,
    force_refresh: bool = False,
) -> dict:
    with TOSS_INFO_CACHE_LOCK:
        cached = TOSS_INFO_CACHE.get(int(match_id))
    now_ts = time.time()
    if not toss_time:
        try:
            match_row = data_service.get_match_by_id(int(match_id))
            toss_time = toss_time or (match_row or {}).get("toss_time")
        except Exception:
            toss_time = toss_time or None
    if cached:
        if cached.get("announced"):
            return _copy_toss_payload(cached["payload"])
        if not force_refresh and now_ts - cached.get("fetched_at", 0) < TOSS_INFO_TTL_SECONDS:
            return _copy_toss_payload(cached["payload"])

    if not should_attempt_toss_fetch(match_date, match_time, toss_time):
        payload = {"announced": False, "team": None, "decision": None, "text": "", "url": ""}
        with TOSS_INFO_CACHE_LOCK:
            TOSS_INFO_CACHE[int(match_id)] = {
                "payload": payload,
                "fetched_at": now_ts,
                "announced": False,
            }
        return _copy_toss_payload(payload)

    try:
        cricbuzz_match_id = data_service.get_stored_cricbuzz_match_id(int(match_id))
        if not cricbuzz_match_id:
            cricbuzz_match_id = resolve_cricbuzz_match_id(int(match_id), team1, team2)
    except Exception as exc:
        print(f"[Toss] Match {match_id}: match id lookup failed: {exc}")
        cricbuzz_match_id = None
    if not cricbuzz_match_id:
        print(f"[Toss] Match {match_id}: no Cricbuzz match id found")
        payload = {"announced": False, "team": None, "decision": None, "text": "", "url": ""}
        with TOSS_INFO_CACHE_LOCK:
            TOSS_INFO_CACHE[int(match_id)] = {
                "payload": payload,
                "fetched_at": now_ts,
                "announced": False,
            }
        return _copy_toss_payload(payload)

    commentary_url = build_cricbuzz_commentary_url(cricbuzz_match_id)
    scorecard_url = f"https://www.cricbuzz.com/live-cricket-scorecard/{cricbuzz_match_id}"
    print(
        f"[Toss] Match {match_id}: trying commentary_url={commentary_url} "
        f"scorecard_url={scorecard_url}"
    )

    for url in (commentary_url, scorecard_url):
        try:
            res = _session_get(url)
            if res.status_code != 200:
                if team1 and team2:
                    refreshed_match_id = resolve_cricbuzz_match_id(int(match_id), team1, team2, force_refresh=True)
                    if refreshed_match_id and refreshed_match_id != cricbuzz_match_id:
                        cricbuzz_match_id = refreshed_match_id
                        retry_url = build_cricbuzz_commentary_url(cricbuzz_match_id) if url == commentary_url else f"https://www.cricbuzz.com/live-cricket-scorecard/{cricbuzz_match_id}"
                        retry_res = _session_get(retry_url)
                        if retry_res.status_code == 200:
                            parsed = _extract_toss_info_from_html(retry_res.text, team1, team2)
                            if parsed:
                                parsed["url"] = retry_url
                                with TOSS_INFO_CACHE_LOCK:
                                    TOSS_INFO_CACHE[int(match_id)] = {
                                        "payload": parsed,
                                        "fetched_at": now_ts,
                                        "announced": True,
                                    }
                                return _copy_toss_payload(parsed)
                continue
            parsed = _extract_toss_info_from_html(res.text, team1, team2)
            if parsed:
                parsed["url"] = url
                with TOSS_INFO_CACHE_LOCK:
                    TOSS_INFO_CACHE[int(match_id)] = {
                        "payload": parsed,
                        "fetched_at": now_ts,
                        "announced": True,
                    }
                return _copy_toss_payload(parsed)
        except Exception as exc:
            print(f"[Toss] Match {match_id}: error fetching {url}: {exc}")

    payload = {"announced": False, "team": None, "decision": None, "text": "", "url": ""}
    with TOSS_INFO_CACHE_LOCK:
        TOSS_INFO_CACHE[int(match_id)] = {
            "payload": payload,
            "fetched_at": now_ts,
            "announced": False,
        }
    return _copy_toss_payload(payload)


def fetch_venues_from_cricbuzz() -> dict[int, str]:
    """Fetch venue info for all matches from Cricbuzz schedule. Returns {match_no: 'Ground, City'}. Fails silently."""
    try:
        schedule_url = build_cricbuzz_schedule_url()
        res = _session_get(schedule_url)
        if res.status_code != 200:
            return {}

        venues: dict[int, str] = {}
        data = _extract_cricbuzz_embedded_json(res.text, "matchesData")
        if not data:
            return {}

        for section in data.get("matchDetails", []):
            match_map = section.get("matchDetailsMap", {})
            for match in match_map.get("match", []):
                match_info = match.get("matchInfo", {})
                match_desc = str(match_info.get("matchDesc", ""))
                desc_match = re.match(r"(\d+)(?:st|nd|rd|th)? Match\b", match_desc, flags=re.IGNORECASE)
                if not desc_match:
                    continue

                match_no = int(desc_match.group(1))
                venue_info = match_info.get("venueInfo", {})
                ground = venue_info.get("ground", "")
                city = venue_info.get("city", "")
                if ground:
                    venues[match_no] = f"{ground}, {city}" if city else ground

        print(f"[Cricbuzz] Fetched venues for {len(venues)} matches")
        return venues
    except Exception as e:
        print(f"[Cricbuzz] Error fetching venues: {e}")
        return {}


def sync_match_metadata_from_schedule(db=None) -> dict[str, int]:
    """Backfill cached match metadata from the schedule page when needed."""
    close_db = False
    if db is None:
        db = data_service.get_db()
        close_db = False

    rows = db.execute(
        """
        SELECT id, team1, team2, match_date, match_time, cricbuzz_match_id, espn_match_id, toss_time
        FROM matches
        """
    ).fetchall()

    updated_toss_times = 0
    updated_cricbuzz_ids = 0
    updated_espn_ids = 0
    missing_cricbuzz_rows: list[dict] = []
    missing_espn_rows: list[dict] = []

    for row in rows:
        match_id = int(row["id"])
        computed_toss_time = compute_toss_time(row["match_date"], row["match_time"])
        if computed_toss_time and row["toss_time"] != computed_toss_time:
            db.execute(
                "UPDATE matches SET toss_time = ? WHERE id = ?",
                (computed_toss_time, match_id),
            )
            updated_toss_times += 1

        if row["cricbuzz_match_id"] in (None, ""):
            missing_cricbuzz_rows.append(dict(row))
        if row["espn_match_id"] in (None, ""):
            missing_espn_rows.append(dict(row))

    schedule_lookup = None
    if missing_cricbuzz_rows:
        schedule_lookup = _fetch_cricbuzz_schedule_lookup()

    if schedule_lookup:
        for row in missing_cricbuzz_rows:
            match_id = int(row["id"])
            key = _normalize_cricbuzz_match_key(match_id, row["team1"], row["team2"])
            cricbuzz_match_id = schedule_lookup.get(key)
            if not cricbuzz_match_id:
                continue
            db.execute(
                "UPDATE matches SET cricbuzz_match_id = ? WHERE id = ?",
                (int(cricbuzz_match_id), match_id),
            )
            CRICBUZZ_MATCH_ID_MAP[match_id] = int(cricbuzz_match_id)
            updated_cricbuzz_ids += 1

    espn_schedule_lookup = None
    if missing_espn_rows:
        espn_schedule_lookup = _fetch_espn_schedule_lookup()

    if espn_schedule_lookup:
        for row in missing_espn_rows:
            match_id = int(row["id"])
            key = _normalize_espn_match_key(match_id, row["team1"], row["team2"])
            espn_match_id = espn_schedule_lookup.get(key)
            if not espn_match_id:
                continue
            db.execute(
                "UPDATE matches SET espn_match_id = ? WHERE id = ?",
                (int(espn_match_id), match_id),
            )
            ESPN_MATCH_ID_MAP[match_id] = int(espn_match_id)
            updated_espn_ids += 1

    if updated_toss_times or updated_cricbuzz_ids or updated_espn_ids:
        db.commit()
        try:
            data_service.invalidate_cache("matches")
        except Exception:
            pass
        try:
            from backend.routes.matches import invalidate_matches_response_cache
            invalidate_matches_response_cache()
        except Exception:
            pass

    return {
        "toss_time": updated_toss_times,
        "cricbuzz_match_id": updated_cricbuzz_ids,
        "espn_match_id": updated_espn_ids,
    }


def get_cached_toss_info(match_id: int) -> dict | None:
    with TOSS_INFO_CACHE_LOCK:
        cached = TOSS_INFO_CACHE.get(int(match_id))
    if not cached:
        return None
    return _copy_toss_payload(cached["payload"])


def is_cached_toss_announced(match_id: int) -> bool:
    with TOSS_INFO_CACHE_LOCK:
        cached = TOSS_INFO_CACHE.get(int(match_id))
    return bool(cached and cached.get("announced"))


def invalidate_live_metadata_cache(match_id: int | None = None) -> None:
    with acquire_cache_locks("scraper_playing_xi", "scraper_toss_info"):
        if match_id is None:
            PLAYING_XI_CACHE.clear()
            TOSS_INFO_CACHE.clear()
            return
        PLAYING_XI_CACHE.pop(int(match_id), None)
        TOSS_INFO_CACHE.pop(int(match_id), None)


def populate_match_venues(db) -> None:
    """Populate venue column in matches table from Cricbuzz. Fails silently."""
    try:
        # Check which matches are missing venue
        rows = db.execute("SELECT id FROM matches WHERE venue IS NULL OR venue = ''").fetchall()
        if not rows:
            return

        missing_ids = {r["id"] for r in rows}
        venues = fetch_venues_from_cricbuzz()
        if not venues:
            return

        updated = 0
        for match_no, venue_str in venues.items():
            if match_no in missing_ids:
                db.execute("UPDATE matches SET venue = ? WHERE id = ?", (venue_str, match_no))
                updated += 1

        if updated:
            db.commit()
            from backend.services import data_service
            from backend.routes.matches import invalidate_matches_response_cache
            from backend.services.venue_stats import invalidate_today_venue_cache

            data_service.invalidate_cache("matches")
            invalidate_matches_response_cache()
            invalidate_today_venue_cache()
            print(f"[Venues] Updated venue for {updated} matches")
    except Exception as e:
        print(f"[Venues] Error populating venues: {e}")
