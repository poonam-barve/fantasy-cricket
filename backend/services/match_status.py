from __future__ import annotations

from datetime import datetime, timedelta

from backend.config import IST, get_current_datetime


def resolve_match_status(match_date: str, match_time: str, stored_status: str | None, toss_time: str | None = None) -> tuple[str, bool]:
    try:
        match_datetime = datetime.strptime(f"{match_date} {match_time}", "%Y-%m-%d %H:%M")
        match_datetime = IST.localize(match_datetime)
    except Exception:
        return "future", False

    now = get_current_datetime()
    normalized_status = (stored_status or "").strip().lower()

    if normalized_status in {"completed", "nr"}:
        return normalized_status, True

    window_start = match_datetime - timedelta(minutes=30)
    if toss_time:
        try:
            window_start = IST.localize(datetime.strptime(f"{match_date} {toss_time}", "%Y-%m-%d %H:%M"))
        except Exception:
            try:
                window_start = IST.localize(datetime.strptime(toss_time, "%Y-%m-%d %H:%M"))
            except Exception:
                pass

    if now < window_start:
        return "future", False
    if now < match_datetime:
        return "lineups", True

    if normalized_status == "live":
        return "live", True

    if now >= match_datetime + timedelta(hours=5):
        return "completed", True

    return "live", True


def resolve_match_status_from_row(match_row) -> tuple[str, bool]:
    if not match_row:
        return "future", False

    if isinstance(match_row, dict):
        match_date = match_row.get("match_date") or match_row.get("Date") or ""
        match_time = match_row.get("match_time") or match_row.get("Time") or ""
        stored_status = match_row.get("status") or match_row.get("Status")
        toss_time = match_row.get("toss_time") or match_row.get("TossTime")
    else:
        match_date = match_row["match_date"] if "match_date" in match_row.keys() else match_row["Date"]
        match_time = match_row["match_time"] if "match_time" in match_row.keys() else match_row["Time"]
        stored_status = match_row["status"] if "status" in match_row.keys() else match_row["Status"]
        toss_time = match_row["toss_time"] if "toss_time" in match_row.keys() else match_row["TossTime"]

    return resolve_match_status(str(match_date or ""), str(match_time or ""), stored_status, str(toss_time or "") or None)
