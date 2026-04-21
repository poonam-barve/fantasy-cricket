import time
import threading
import traceback
from datetime import datetime, timedelta

from backend.config import IST
from backend.models.match import Match
from backend.models.team import Team, Contestant
from backend.models.registry import PlayerRegistry
from backend.services.scraper import (
    fetch_playing_xi,
    fetch_toss_info,
    fetch_scorecard_html,
    fetch_cricbuzz_scorecard_html,
    initialize_espn_match_map,
    initialize_cricbuzz_match_map,
    is_cached_toss_announced,
)
from backend.services import data_service
from bs4 import BeautifulSoup

DEBUG_PLAYER_ID = 0


def build_player_role_map(players_data):
    return {int(p["PlayerID"]): p["Role"] for p in players_data}


def _invalidate_leaderboard_cache():
    from backend.routes.leaderboard import invalidate_leaderboard_cache

    invalidate_leaderboard_cache()


def _refresh_leaderboard_cache_once():
    from backend.routes.leaderboard import refresh_leaderboard_cache_once

    return refresh_leaderboard_cache_once()


def _invalidate_matches_response_cache():
    from backend.routes.matches import invalidate_matches_response_cache

    invalidate_matches_response_cache()


class Tournament:
    def __init__(self):
        self.matches = {}
        self.match_rows = {}
        self.contestants = {}
        self.match_participants = {}
        self.locked_match_ids_loaded = set()
        self.registry = None
        self.player_roles = {}
        self.player_points = {}
        self.players_by_team = {}

    def initialize(self, players_data, matches_data, teams_data):
        self.refresh_static_data(players_data, matches_data, refresh_schedule_map=True)

        self.contestants = {}
        self.match_participants = {}
        self.locked_match_ids_loaded = set()
        if teams_data:
            self.load_teams(teams_data)
        self.sync_persistent_match_statuses()

    def refresh_static_data(self, players_data, matches_data, refresh_schedule_map=False):
        self.registry = PlayerRegistry(players_data)
        self.player_roles = build_player_role_map(players_data)
        if refresh_schedule_map:
            initialize_cricbuzz_match_map(matches_data)
            initialize_espn_match_map(matches_data)
        self.players_by_team = {}
        for player in players_data:
            self.players_by_team.setdefault(player["Team"], []).append({
                "id": int(player["PlayerID"]),
                "name": player.get("Name", ""),
                "team": player.get("Team", ""),
                "role": player.get("Role", ""),
                "type": player.get("Type"),
                "aliases": player.get("Aliases", ""),
            })

        self.matches = {}
        self.match_rows = {}
        for m in matches_data:
            match_id = str(m["MatchID"])
            self.matches[match_id] = Match(match_id, m["Team1"], m["Team2"], self.registry, m.get("Date") or m.get("match_date"))
            self.match_rows[match_id] = m

    def load_teams(self, teams_data):
        self.contestants = {}
        self.match_participants = {}
        self.locked_match_ids_loaded = set()

        for row in teams_data:
            self._apply_team_row(row)

        self.locked_match_ids_loaded.update(self.match_participants.keys())

    def _apply_team_row(self, row):
        contestant_key = str(row.get("UserID") or row.get("Mobile") or row.get("User"))
        match_id = str(row["MatchID"])
        pid = int(row["PlayerID"])

        if contestant_key not in self.contestants:
            self.contestants[contestant_key] = Contestant(
                row["User"],
                str(row.get("Mobile") or ""),
                row.get("UserID"),
                bool(row.get("IsActive", True)),
            )

        contestant = self.contestants[contestant_key]
        contestant.is_active = bool(row.get("IsActive", True))
        if match_id not in contestant.teams:
            contestant.teams[match_id] = Team(match_id)

        team = contestant.teams[match_id]
        team.player_ids.add(pid)
        self.match_participants.setdefault(match_id, set()).add(contestant_key)

        if str(row["Captain"]).lower() == "true":
            team.captain = pid
        if str(row["ViceCaptain"]).lower() == "true":
            team.vice_captain = pid

    def _remove_match_teams(self, match_id):
        participant_keys = list(self.match_participants.get(match_id, set()))
        for contestant_key in participant_keys:
            contestant = self.contestants.get(contestant_key)
            if not contestant:
                continue
            contestant.teams.pop(match_id, None)
            contestant.points.pop(match_id, None)
            if not contestant.teams:
                self.contestants.pop(contestant_key, None)
        self.match_participants.pop(match_id, None)
        self.locked_match_ids_loaded.discard(match_id)

    def ensure_match_teams_loaded(self, match_ids, force=False):
        normalized_ids = [str(match_id) for match_id in match_ids]
        if not normalized_ids:
            return

        if force:
            for match_id in normalized_ids:
                self._remove_match_teams(match_id)
            ids_to_fetch = normalized_ids
        else:
            ids_to_fetch = [match_id for match_id in normalized_ids if match_id not in self.locked_match_ids_loaded]

        if not ids_to_fetch:
            return

        rows = data_service.get_teams_for_matches(ids_to_fetch)
        for row in rows:
            self._apply_team_row(row)

        self.locked_match_ids_loaded.update(ids_to_fetch)

    def _log_active_player_count(self, match_id, match):
        active_players = [player for player in match.players.values() if getattr(player, "played", False)]
        active_count = len(active_players)
        if active_count < 22 or active_count > 24:
            print(f"[ALERT] Match {match_id}: active scoring player count is {active_count} (expected 22 to 24)")

    def _set_persistent_match_status(self, match_id: str, status: str) -> bool:
        changed = data_service.update_match_status(int(match_id), status)
        if not changed:
            return False

        if match_id in self.match_rows:
            self.match_rows[match_id]["Status"] = status

        if status == "nr":
            data_service.clear_points_for_match(int(match_id))
            self.player_points.pop(match_id, None)
            for contestant in self.contestants.values():
                contestant.points.pop(match_id, None)

        _invalidate_leaderboard_cache()
        _invalidate_matches_response_cache()
        return True

    def _finalize_completed_match(self, match_id: str, reason: str = "scorecard completion") -> bool:
        changed = self._set_persistent_match_status(match_id, "completed")
        if not changed:
            return False

        self.compute_player_points_for_match(match_id)
        self.compute_points_for_match(match_id)

        try:
            self.persist_player_points_to_local()
            self.persist_to_local()
        except Exception as exc:
            self._scheduler_log("SCORE", f"persist after completion failed for match {match_id}: {exc}")
            traceback.print_exc()

        try:
            summary = _refresh_leaderboard_cache_once()
            self._scheduler_log(
                "SCORE",
                f"leaderboard cache refreshed after match {match_id} completion "
                f"({reason}) leaderboard={summary['leaderboard']} points_table={summary['points_table']}",
            )
        except Exception as exc:
            self._scheduler_log("SCORE", f"leaderboard refresh after completion failed for match {match_id}: {exc}")
            traceback.print_exc()

        # Weekend tournament hook
        try:
            from backend.services.weekend_tournament_service import on_match_completed
            on_match_completed(int(match_id))
        except Exception as exc:
            self._scheduler_log("SCORE", f"weekend tournament hook failed for match {match_id}: {exc}")

        return True

    def sync_persistent_match_statuses(self, match_rows=None):
        rows = match_rows or list(self.match_rows.values())
        changed = 0
        for match_row in rows:
            match_id = str(match_row.get("MatchID") or match_row.get("id") or "")
            if not match_id:
                continue
            status = self.get_match_status(match_row)
            if status in {"live", "completed", "nr"}:
                if self._set_persistent_match_status(match_id, status):
                    changed += 1
        return changed

    def _has_match_started(self, match_row) -> bool:
        try:
            match_datetime = datetime.strptime(
                f"{match_row['Date']} {match_row['Time']}", "%Y-%m-%d %H:%M"
            )
            match_datetime = IST.localize(match_datetime)
        except Exception:
            return True
        return datetime.now(IST) >= match_datetime

    def update_match_data(self, match_id, use_playing_xi=False, include_scorecards=True, force_refresh_playing_xi=False):
        match = self.matches.get(match_id)
        if not match:
            return

        match.players = {}

        players_rows = self.players_by_team.get(match.team1, []) + self.players_by_team.get(match.team2, [])

        if use_playing_xi:
            match_row = self.match_rows.get(match_id, {})
            playing_xi = fetch_playing_xi(
                int(match_id),
                match.team1,
                match.team2,
                players_rows,
                match_row.get("Date"),
                match_row.get("Time"),
                match_row.get("TossTime") or match_row.get("toss_time"),
                force_refresh=force_refresh_playing_xi,
            )
            playing_ids = playing_xi.get("player_ids", [])
            substitute_ids = playing_xi.get("substitute_ids", [])
            print(f"[Playing XI] Match {match_id}: fetch result url={playing_xi.get('url')} players={len(playing_ids)}")
            if len(playing_ids) == 22 and len(substitute_ids) == 10:
                swaps_applied = data_service.apply_backups_for_match(match_id, playing_ids, substitute_ids)
                if swaps_applied:
                    print(f"[Backups] Match {match_id}: applied {swaps_applied} backup swaps")
                    self.ensure_match_teams_loaded([match_id], force=True)
            if playing_ids:
                match.apply_playing_xi(playing_ids)

                team1_players = sorted(
                    [match.players[int(pid)].name for pid in playing_ids if self.registry.players.get(int(pid), {}).get("Team") == match.team1]
                )
                team2_players = sorted(
                    [match.players[int(pid)].name for pid in playing_ids if self.registry.players.get(int(pid), {}).get("Team") == match.team2]
                )
                print(f"[Playing XI] Match {match_id} via {playing_xi.get('url')}")
                print(f"  {match.team1}: {', '.join(team1_players) if team1_players else 'none'}")
                print(f"  {match.team2}: {', '.join(team2_players) if team2_players else 'none'}")
            else:
                print(f"[Playing XI] Match {match_id}: no mapped playing XI players found")

        if not include_scorecards:
            return

        cricbuzz_html = fetch_cricbuzz_scorecard_html(int(match_id), match.team1, match.team2)
        if cricbuzz_html:
            match.parse_cricbuzz_scorecard_html(cricbuzz_html, reset_players=False)

        espn_html_text = fetch_scorecard_html(int(match_id), match.team1, match.team2)
        if espn_html_text:
            soup = BeautifulSoup(espn_html_text, "html.parser")
            match.parse_espn_bowling_dot_balls(soup)
            self._log_active_player_count(match_id, match)

        completion_state = getattr(match, "get_scorecard_completion_state", lambda: None)()
        if completion_state and completion_state.get("status") == "completed":
            reason = completion_state.get("reason", "scorecard completion")
            self._scheduler_log("SCORE", f"match {match_id} completed from scorecard ({reason})")
            return self._finalize_completed_match(match_id, reason)

        return False

    def get_match_status(self, match_row):
        try:
            match_datetime = datetime.strptime(
                f"{match_row['Date']} {match_row['Time']}", "%Y-%m-%d %H:%M"
            )
            match_datetime = IST.localize(match_datetime)
        except Exception:
            return None

        now = datetime.now(IST)

        stored_status = str(match_row.get("Status") or "").strip().lower()
        toss_time = str(match_row.get("TossTime") or match_row.get("toss_time") or "").strip()
        if toss_time:
            try:
                window_start = IST.localize(datetime.strptime(f"{match_row['Date']} {toss_time}", "%Y-%m-%d %H:%M"))
            except Exception:
                try:
                    window_start = IST.localize(datetime.strptime(toss_time, "%Y-%m-%d %H:%M"))
                except Exception:
                    window_start = match_datetime - timedelta(minutes=30)
        else:
            window_start = match_datetime - timedelta(minutes=30)

        if stored_status in {"completed", "nr"}:
            return stored_status

        if now < window_start:
            return "future"
        if now < match_datetime:
            return "lineups"

        if stored_status == "live":
            return "live"

        if now >= match_datetime + timedelta(hours=5):
            return "completed"

        return "live"

    def compute_player_points_for_match(self, match_id):
        match = self.matches.get(match_id)
        if not match:
            return
        player_points = {}
        for pid, player in match.players.items():
            role = self.player_roles.get(pid)
            if role:
                player_points[pid] = player.calculate_player_points(role)
                if DEBUG_PLAYER_ID and int(pid) == DEBUG_PLAYER_ID:
                    print(
                        f"[DEBUG player {DEBUG_PLAYER_ID}]",
                        {
                            "match_id": match_id,
                            "player_id": pid,
                            "name": player.name,
                            "team": player.team,
                            "role": role,
                            "played": player.played,
                            "runs": player.runs,
                            "balls": player.balls,
                            "fours": player.fours,
                            "sixes": player.sixes,
                            "strike_rate": player.strike_rate,
                            "overs": player.overs,
                            "maidens": player.maidens,
                            "runs_conceded": player.runs_conceded,
                            "wickets": player.wickets,
                            "dot_balls": player.dot_balls,
                            "bowled": player.bowled,
                            "lbw": player.lbw,
                            "economy": player.economy,
                            "catches": player.catches,
                            "runout_direct": player.runout_direct,
                            "runout_indirect": player.runout_indirect,
                            "stumpings": player.stumpings,
                            "dismissal": player.dismissal,
                            "is_out": player.is_out,
                            "points": player_points[pid],
                        },
                    )
        self.player_points[match_id] = player_points

    def compute_points_for_match(self, match_id):
        participant_keys = self.match_participants.get(match_id, set())
        match = self.matches.get(match_id)
        if not match:
            return

        for contestant_key in participant_keys:
            contestant = self.contestants.get(contestant_key)
            if not contestant:
                continue
            if not contestant.is_active:
                contestant.points.pop(match_id, None)
                continue
            contestant.calculate_points_for_match(match, self.player_roles)

    def persist_to_local(self):
        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        data_service.delete_inactive_contestant_points()
        rows = []
        for contestant in self.contestants.values():
            if not contestant.is_active:
                continue
            for match_id, pts in contestant.points.items():
                rows.append({
                    "UserID": contestant.user_id,
                    "User": contestant.name,
                    "Mobile": contestant.mobile,
                    "MatchID": match_id,
                    "Points": round(pts, 2),
                    "LastUpdated": now_str,
                })
        if rows:
            data_service.save_contestant_points(rows)

    def persist_player_points_to_local(self):
        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        rows = []
        for match_id, pp in self.player_points.items():
            match = self.matches.get(match_id)
            if not match:
                continue
            for pid, points in pp.items():
                player = match.players.get(pid)
                info = self.registry.players.get(pid)
                if not info:
                    continue
                rows.append({
                    "MatchID": match_id,
                    "PlayerID": pid,
                    "PlayerName": player.name if player else "",
                    "Team": info.get("Team", ""),
                    "Role": info.get("Role", ""),
                    "Points": round(points, 2),
                    "LastUpdated": now_str,
                })
        if rows:
            data_service.save_player_points(rows)
            data_service.invalidate_match_player_payloads()

    def recompute_completed_matches(self, reason: str = "manual", include_nr: bool = False):
        print(f"\n--- Completed matches recompute ({reason}) ---")
        players_data = data_service.get_cached_data("players")
        matches_data = data_service.get_cached_data("matches")
        self.refresh_static_data(players_data, matches_data, refresh_schedule_map=True)

        statuses_to_include = {"completed"}
        if include_nr:
            statuses_to_include.add("nr")

        terminal_match_ids = [
            str(match_row["MatchID"])
            for match_row in matches_data
            if self.get_match_status(match_row) in statuses_to_include
        ]

        if not terminal_match_ids:
            _invalidate_leaderboard_cache()
            _invalidate_matches_response_cache()
            print("  No terminal matches found for recompute")
            return 0

        self.ensure_match_teams_loaded(terminal_match_ids, force=True)

        processed = 0
        needs_persist = False
        for match_id in terminal_match_ids:
            try:
                print(f"  Match {match_id}: terminal status - revalidating scorecard")
                finalized_from_scorecard = self.update_match_data(
                    match_id,
                    use_playing_xi=True,
                    include_scorecards=True,
                    force_refresh_playing_xi=True,
                )
                if finalized_from_scorecard:
                    processed += 1
                    continue
                if self.get_match_status(self.match_rows.get(match_id, {})) != "completed":
                    continue
                self.compute_player_points_for_match(match_id)
                self.compute_points_for_match(match_id)
                needs_persist = True
                processed += 1
            except Exception as exc:
                print(f"  Match {match_id}: ERROR - {exc}")
                traceback.print_exc()

        if needs_persist:
            self.persist_player_points_to_local()
            self.persist_to_local()
            try:
                summary = _refresh_leaderboard_cache_once()
                self._scheduler_log(
                    "SCORE",
                    f"leaderboard cache refreshed after recompute leaderboard={summary['leaderboard']} points_table={summary['points_table']}",
                )
            except Exception as exc:
                self._scheduler_log("SCORE", f"leaderboard refresh after recompute failed: {exc}")
                traceback.print_exc()

        _invalidate_matches_response_cache()
        print(f"  Recomputed {processed} completed matches")
        return processed

    def _scheduler_log(self, channel: str, message: str):
        timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{channel}] {message}")

    def refresh_scores_once(self):
        matches_data = data_service.get_cached_data("matches")
        computed_matches = data_service.get_computed_match_ids()
        locked_match_ids_to_load = []

        for m in matches_data:
            match_id = str(m["MatchID"])
            status = self.get_match_status(m)
            if status == "live":
                locked_match_ids_to_load.append(match_id)
            elif status == "completed" and match_id not in computed_matches:
                locked_match_ids_to_load.append(match_id)

        self._scheduler_log(
            "SCORE",
            f"tick matches={len(matches_data)} load={len(locked_match_ids_to_load)} computed={len(computed_matches)}",
        )

        self.ensure_match_teams_loaded(locked_match_ids_to_load)
        self.sync_persistent_match_statuses(matches_data)

        processed = 0
        needs_persist = False
        for m in matches_data:
            match_id = str(m["MatchID"])
            status = self.get_match_status(m)

            if status == "future":
                continue

            try:
                if status == "lineups":
                    self._scheduler_log("SCORE", f"match {match_id} lineups -> refreshing score cache")
                    finalized_from_scorecard = self.update_match_data(
                        match_id,
                        use_playing_xi=True,
                        include_scorecards=False,
                        force_refresh_playing_xi=True,
                    )
                    if finalized_from_scorecard:
                        processed += 1
                        continue
                elif status == "live":
                    self._scheduler_log("SCORE", f"match {match_id} live -> refreshing scores")
                    finalized_from_scorecard = self.update_match_data(
                        match_id,
                        use_playing_xi=True,
                        include_scorecards=True,
                        force_refresh_playing_xi=True,
                    )
                    if finalized_from_scorecard:
                        processed += 1
                        continue
                    updated_status = self.get_match_status(self.match_rows.get(match_id, {}))
                    if updated_status == "nr":
                        continue
                    self.compute_player_points_for_match(match_id)
                    self.compute_points_for_match(match_id)
                    needs_persist = True
                    processed += 1
                elif status == "completed":
                    if match_id in computed_matches:
                        continue
                    self._scheduler_log("SCORE", f"match {match_id} completed -> revalidating")
                    finalized_from_scorecard = self.update_match_data(
                        match_id,
                        use_playing_xi=True,
                        include_scorecards=True,
                        force_refresh_playing_xi=True,
                    )
                    if finalized_from_scorecard:
                        processed += 1
                        continue
                    updated_status = self.get_match_status(self.match_rows.get(match_id, {}))
                    if updated_status != "completed":
                        continue
                    self.compute_player_points_for_match(match_id)
                    self.compute_points_for_match(match_id)
                    needs_persist = True
                    processed += 1
            except Exception as e:
                self._scheduler_log("SCORE", f"match {match_id} error: {e}")
                traceback.print_exc()

        if needs_persist:
            self.persist_player_points_to_local()
            self.persist_to_local()
            try:
                summary = _refresh_leaderboard_cache_once()
                self._scheduler_log(
                    "SCORE",
                    f"leaderboard cache refreshed leaderboard={summary['leaderboard']} points_table={summary['points_table']}",
                )
            except Exception as exc:
                self._scheduler_log("SCORE", f"leaderboard refresh failed: {exc}")
                traceback.print_exc()

        return {
            "eligible": len(locked_match_ids_to_load),
            "processed": processed,
            "matches": len(matches_data),
        }

    def refresh_lineup_cache_once(self):
        matches_data = data_service.get_cached_data("matches")
        lineup_match_ids = []

        for m in matches_data:
            match_id = str(m["MatchID"])
            status = self.get_match_status(m)
            if status in {"lineups", "live"}:
                lineup_match_ids.append(match_id)

        self._scheduler_log("XI", f"tick matches={len(matches_data)} eligible={len(lineup_match_ids)}")

        if not lineup_match_ids:
            return {"eligible": 0, "refreshed": 0, "finalized": 0}

        self.ensure_match_teams_loaded(lineup_match_ids)
        refreshed = 0
        finalized = 0
        for match_id in lineup_match_ids:
            try:
                match_row = self.match_rows.get(match_id, {})
                if data_service.is_cached_playing_xi_final(
                    int(match_id),
                    match_row.get("Team1", ""),
                    match_row.get("Team2", ""),
                    match_row.get("Date", ""),
                    match_row.get("Time", ""),
                ):
                    finalized += 1
                    self._scheduler_log("XI", f"match {match_id} already finalized, skipping")
                    continue
                self._scheduler_log("XI", f"match {match_id} refreshing XI cache")
                self.update_match_data(
                    match_id,
                    use_playing_xi=True,
                    include_scorecards=False,
                    force_refresh_playing_xi=True,
                )
                refreshed += 1
            except Exception as exc:
                self._scheduler_log("XI", f"match {match_id} refresh error: {exc}")
                traceback.print_exc()

        return {"eligible": len(lineup_match_ids), "refreshed": refreshed, "finalized": finalized}

    def refresh_toss_cache_once(self):
        matches_data = data_service.get_cached_data("matches")
        toss_match_ids = []

        for m in matches_data:
            match_id = str(m["MatchID"])
            status = self.get_match_status(m)
            if status == "lineups":
                toss_match_ids.append(match_id)

        self._scheduler_log("TOSS", f"tick matches={len(matches_data)} eligible={len(toss_match_ids)}")

        if not toss_match_ids:
            return {"eligible": 0, "refreshed": 0, "announced": 0}

        self.ensure_match_teams_loaded(toss_match_ids)
        refreshed = 0
        announced = 0
        for match_id in toss_match_ids:
            try:
                match_row = self.match_rows.get(match_id, {})
                if is_cached_toss_announced(int(match_id)):
                    announced += 1
                    self._scheduler_log("TOSS", f"match {match_id} already announced, skipping")
                    continue
                match_obj = self.matches.get(match_id)
                if not match_obj:
                    self._scheduler_log("TOSS", f"match {match_id} has no match object, skipping")
                    continue
                self._scheduler_log("TOSS", f"match {match_id} refreshing toss cache")
                fetch_toss_info(
                    int(match_id),
                    match_obj.team1,
                    match_obj.team2,
                    match_row.get("Date"),
                    match_row.get("Time"),
                    match_row.get("TossTime") or match_row.get("toss_time"),
                    force_refresh=True,
                )
                refreshed += 1
            except Exception as exc:
                self._scheduler_log("TOSS", f"match {match_id} refresh error: {exc}")
                traceback.print_exc()

        return {"eligible": len(toss_match_ids), "refreshed": refreshed, "announced": announced}

    def start_scheduler(self):
        def run():
            while True:
                try:
                    self._scheduler_log("SCORE", "scheduler tick start")
                    summary = self.refresh_scores_once()
                    if summary["processed"] > 0:
                        self._scheduler_log("SCORE", f"persisted matches={summary['processed']}")
                except Exception as e:
                    self._scheduler_log("SCORE", f"scheduler outer error: {e}")
                    traceback.print_exc()

                time.sleep(60)

        thread = threading.Thread(target=run, daemon=True, name="score-scheduler")
        thread.start()

    def start_lineup_cache_scheduler(self):
        def run():
            while True:
                try:
                    summary = self.refresh_lineup_cache_once()
                    time.sleep(15 if summary["eligible"] else 30)
                except Exception as e:
                    self._scheduler_log("XI", f"scheduler error: {e}")
                    traceback.print_exc()
                    time.sleep(30)

        thread = threading.Thread(target=run, daemon=True, name="lineup-cache-scheduler")
        thread.start()

    def start_toss_cache_scheduler(self):
        def run():
            while True:
                try:
                    summary = self.refresh_toss_cache_once()
                    time.sleep(15 if summary["eligible"] else 30)
                except Exception as e:
                    self._scheduler_log("TOSS", f"scheduler error: {e}")
                    traceback.print_exc()
                    time.sleep(30)

        thread = threading.Thread(target=run, daemon=True, name="toss-cache-scheduler")
        thread.start()
