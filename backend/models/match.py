import re
import json
import logging
from bs4 import BeautifulSoup
from backend.models.player import Player
from backend.models.registry import PlayerRegistry
from backend.config import TEAM_MAP
from backend.services import data_service


logger = logging.getLogger(__name__)


def clean_name(name):
    name = re.sub(r"[\u2020\u2021*]", "", str(name))
    name = re.sub(r"\s*\((?:c|wk|w|sub)\)\s*$", "", name, flags=re.IGNORECASE)
    return " ".join(name.split()).strip()


def clean_team_name(name):
    name = re.sub(r"\(.*?\)", "", name).strip()
    name = " ".join(name.split())
    short = TEAM_MAP.get(name)
    if short:
        return short
    logger.debug("Team mapping missing for: %s", name)
    return name


class Match:
    def __init__(self, match_id, team1, team2, registry: PlayerRegistry, match_date: str | None = None):
        self.match_id = match_id
        self.team1 = team1
        self.team2 = team2
        self.registry = registry
        self.match_date = match_date or ""
        self.players = {}  # pid -> Player
        self.scorecard = []

    def get_player_id(self, name, team):
        cleaned_name = clean_name(name)
        if cleaned_name.lower() in {"", "not out", "batting"}:
            return None
        normalized_name = self.registry.normalize(cleaned_name)

        # Exact full-name/alias lookup must win before any ambiguity fallback.
        if (team, normalized_name) in self.registry.lookup:
            return self.registry.lookup[(team, normalized_name)]

        direct_pid = self.registry.get_player_id(cleaned_name, team)
        candidates = self.registry.get_player_candidates(cleaned_name, team)

        if len(candidates) <= 1:
            if not direct_pid:
                try:
                    data_service.log_unknown_player(
                        cleaned_name,
                        team,
                        int(self.match_id),
                        self.match_date,
                        self.team1,
                        self.team2,
                    )
                except Exception:
                    pass
            return direct_pid

        playing_candidates = []
        for pid in candidates:
            player = self.players.get(pid)
            if player and getattr(player, "played", False):
                playing_candidates.append(pid)

        if len(playing_candidates) == 1:
            preferred_pid = playing_candidates[0]
            if direct_pid != preferred_pid:
                print(
                    f"[Match {self.match_id}] Preferred playing XI player for '{cleaned_name}' "
                    f"({team}): {self.registry.players.get(preferred_pid, {}).get('Name', preferred_pid)}"
                )
            return preferred_pid

        if not direct_pid:
            try:
                data_service.log_unknown_player(
                    cleaned_name,
                    team,
                    int(self.match_id),
                    self.match_date,
                    self.team1,
                    self.team2,
                )
            except Exception:
                pass
        return direct_pid

    def get_or_create_player(self, pid):
        if not pid:
            return None
        if pid not in self.players:
            player_data = self.registry.players.get(pid, {})
            full_name = player_data.get("Name", "Unknown")
            self.players[pid] = Player(pid, full_name)
        return self.players[pid]

    def get_player_by_name(self, name):
        name = clean_name(name)
        team = None
        pid = self.registry.get_player_id(name, self.team1)
        if pid:
            team = self.team1
        else:
            pid = self.registry.get_player_id(name, self.team2)
            if pid:
                team = self.team2
        if not pid:
            return None
        player = self.get_or_create_player(pid)
        if player and team and not player.team:
            player.team = team
        return player

    def get_player_by_team(self, name, team):
        name = clean_name(name)
        pid = self.get_player_id(name, team)
        if not pid:
            return None
        player = self.get_or_create_player(pid)
        if player and not player.team:
            player.team = team
        return player

    def apply_playing_xi(self, player_ids):
        for pid in player_ids:
            player = self.get_or_create_player(int(pid))
            if not player:
                continue
            player.team = self.registry.players.get(int(pid), {}).get("Team")
            player.played = True

    # --- Scorecard parser ---

    def parse_scorecard(self, soup, reset_players=True):
        if reset_players:
            self.players = {}
        self.parse_espn_scorecard(soup)

    def _sort_data_keys(self, key):
        match = re.search(r"_(\d+)$", str(key))
        return int(match.group(1)) if match else 10**9

    def _extract_cricbuzz_scorecard_payload(self, html_text):
        marker = 'ApiData\\":{'
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
            print(f"[Match {self.match_id}] Failed to parse Cricbuzz scorecard payload: {exc}")
            return None

    def parse_cricbuzz_scorecard_html(self, html_text, reset_players=True):
        if reset_players:
            self.players = {}
        self.scorecard = []

        payload = self._extract_cricbuzz_scorecard_payload(html_text)
        if not payload:
            return False

        innings_list = payload.get("scoreCard", [])
        valid_teams = {self.team1, self.team2}
        parsed_any = False

        for innings in innings_list:
            bat_details = innings.get("batTeamDetails") or {}
            bowl_details = innings.get("bowlTeamDetails") or {}
            score_details = innings.get("scoreDetails") or {}

            def _as_int(value):
                try:
                    return int(float(value))
                except Exception:
                    return None

            def _as_float(value):
                try:
                    return float(value)
                except Exception:
                    return None

            batting_team = clean_team_name(
                bat_details.get("batTeamShortName") or bat_details.get("batTeamName") or ""
            )
            bowling_team = clean_team_name(
                bowl_details.get("bowlTeamShortName") or bowl_details.get("bowlTeamName") or ""
            )

            if batting_team not in valid_teams or bowling_team not in valid_teams:
                continue

            innings_snapshot = {
                "batting_team": batting_team,
                "bowling_team": bowling_team,
                "batting": [],
                "bowling": [],
                "total_runs": _as_int(
                    score_details.get("runs")
                    if "runs" in score_details
                    else innings.get("runs")
                ),
                "total_wickets": _as_int(
                    score_details.get("wickets")
                    if "wickets" in score_details
                    else innings.get("wickets")
                ),
                "total_overs": _as_float(
                    score_details.get("overs")
                    if "overs" in score_details
                    else innings.get("overs")
                ),
            }

            batsmen_data = bat_details.get("batsmenData") or {}
            for key in sorted(batsmen_data, key=self._sort_data_keys):
                batter_data = batsmen_data.get(key) or {}
                batter_name = clean_name(batter_data.get("batName", ""))
                if not batter_name:
                    continue

                pid = self.get_player_id(batter_name, batting_team)
                if not pid:
                    continue

                player = self.get_or_create_player(pid)
                player.team = batting_team
                player.played = True
                player.runs = int(batter_data.get("runs") or 0)
                player.balls = int(batter_data.get("balls") or 0)
                player.fours = int(batter_data.get("fours") or 0)
                player.sixes = int(batter_data.get("sixes") or 0)
                player.strike_rate = float(batter_data.get("strikeRate") or 0)

                dismissal = str(batter_data.get("outDesc") or "").strip()
                if dismissal:
                    player.apply_dismissal(dismissal, self, bowling_team)
                else:
                    player.dismissal = None
                    player.is_out = False

                innings_snapshot["batting"].append({
                    "player_id": int(pid),
                    "name": player.name,
                    "dismissal": player.dismissal or "not out",
                    "is_out": bool(player.is_out),
                    "runs": int(player.runs or 0),
                    "balls": int(player.balls or 0),
                    "fours": int(player.fours or 0),
                    "sixes": int(player.sixes or 0),
                    "strike_rate": float(player.strike_rate or 0),
                })

                if (
                    innings_snapshot["batting"][-1]["balls"] == 0
                    and innings_snapshot["batting"][-1]["runs"] == 0
                    and not innings_snapshot["batting"][-1]["is_out"]
                ):
                    innings_snapshot["batting"].pop()
                    continue

                parsed_any = True

            bowlers_data = bowl_details.get("bowlersData") or {}
            for key in sorted(bowlers_data, key=self._sort_data_keys):
                bowler_data = bowlers_data.get(key) or {}
                bowler_name = clean_name(bowler_data.get("bowlName", ""))
                if not bowler_name:
                    continue

                pid = self.get_player_id(bowler_name, bowling_team)
                if not pid:
                    continue

                player = self.get_or_create_player(pid)
                player.team = bowling_team
                player.played = True
                player.overs = float(bowler_data.get("overs") or 0)
                player.maidens = int(bowler_data.get("maidens") or 0)
                player.runs_conceded = int(bowler_data.get("runs") or 0)
                player.wickets = int(bowler_data.get("wickets") or 0)
                player.economy = float(bowler_data.get("economy") or 0)

                innings_snapshot["bowling"].append({
                    "player_id": int(pid),
                    "name": player.name,
                    "overs": float(player.overs or 0),
                    "maidens": int(player.maidens or 0),
                    "runs_conceded": int(player.runs_conceded or 0),
                    "wickets": int(player.wickets or 0),
                    "economy": float(player.economy or 0),
                })

                parsed_any = True

            # Fallback only when explicit innings totals are unavailable.
            if innings_snapshot["total_runs"] is None:
                innings_snapshot["total_runs"] = int(
                    sum(int(item.get("runs") or 0) for item in innings_snapshot["batting"])
                )
            if innings_snapshot["total_wickets"] is None:
                innings_snapshot["total_wickets"] = int(
                    sum(1 for item in innings_snapshot["batting"] if item.get("is_out"))
                )
            if innings_snapshot["total_overs"] is None:
                innings_snapshot["total_overs"] = round(
                    sum(float(item.get("overs") or 0) for item in innings_snapshot["bowling"]),
                    1,
                )

            self.scorecard.append(innings_snapshot)

        return parsed_any

    def get_scorecard_completion_state(self):
        """Infer completion from parsed innings without any extra fetches."""
        if len(self.scorecard) < 2:
            return None

        first_innings = self.scorecard[0] or {}
        second_innings = self.scorecard[-1] or {}

        try:
            first_total = int(first_innings.get("total_runs") or 0)
            second_total = int(second_innings.get("total_runs") or 0)
            second_wickets = int(second_innings.get("total_wickets") or 0)
            second_overs = float(second_innings.get("total_overs") or 0)
        except Exception:
            return None

        if second_overs == 20:
            return {
                "status": "completed",
                "reason": "second innings reached 20 overs",
            }

        if second_wickets == 10:
            return {
                "status": "completed",
                "reason": "second innings lost 10 wickets",
            }

        if second_total > first_total:
            return {
                "status": "completed",
                "reason": "second innings reached or surpassed first innings total",
            }

        return None

    def parse_espn_bowling_dot_balls(self, soup: BeautifulSoup, source_url: str | None = None):
        lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
        if source_url:
            print(f"[Match {self.match_id}] ESPN dot-ball parse source={source_url}")
        else:
            print(f"[Match {self.match_id}] ESPN dot-ball parse source=<unknown>")

        def _apply_bowling_row(player_name, bowling_team, overs, maidens, runs, wickets, economy, dot_balls=None, player_id=None):
            pid = player_id or self.get_player_id(player_name, bowling_team)
            if not pid:
                return False

            player = self.get_or_create_player(pid)
            if not player:
                return False

            player.team = bowling_team
            player.played = True
            player.overs = overs
            player.maidens = maidens
            player.runs_conceded = runs
            player.wickets = wickets
            player.economy = economy
            if dot_balls is not None and player.dot_balls <= 0:
                player.dot_balls = dot_balls
                print(
                    f"[Match {self.match_id}] ESPN dot balls parsed: "
                    f"{player.name} ({bowling_team}) = {dot_balls}"
                )
            return True

        def _parse_compact_bowling_row(line, bowling_team):
            normalized = " ".join(str(line).strip().split())
            compact_match = re.match(
                r"^(?P<name>.+?)\s+(?P<overs>\d+(?:\.\d+)?)\s+(?P<maidens>\d+)\s+(?P<runs>\d+)\s+(?P<wickets>\d+)\s+(?P<economy>\d+(?:\.\d+)?)\s+(?P<dot_balls>\d+)\s+(?P<fours>\d+)\s+(?P<sixes>\d+)\s+(?P<wd>\d+)\s+(?P<nb>\d+)\s*$",
                normalized,
            )
            if not compact_match:
                return False

            try:
                name = clean_name(compact_match.group("name"))
                overs = float(compact_match.group("overs"))
                maidens = int(compact_match.group("maidens"))
                runs = int(compact_match.group("runs"))
                wickets = int(compact_match.group("wickets"))
                economy = float(compact_match.group("economy"))
                dot_balls = int(compact_match.group("dot_balls"))
            except Exception:
                return False

            if not name or name.upper() in {"BOWLING", "O", "M", "R", "W", "ECON", "0S", "4S", "6S", "WD", "NB"}:
                return False
            if overs < 0 or overs > 4.0:
                return False
            if maidens < 0 or maidens > 4:
                return False
            if runs < 0 or runs > 80:
                return False
            if wickets < 0 or wickets > 5:
                return False
            if dot_balls < 0 or dot_balls > 24:
                return False

            return _apply_bowling_row(name, bowling_team, overs, maidens, runs, wickets, economy, dot_balls=dot_balls)

        def _parse_pipe_bowling_row(line, bowling_team, has_dot_balls_column):
            if "|" not in line:
                return False

            tokens = [token.strip() for token in line.split("|")]
            tokens = [token for token in tokens if token]
            if len(tokens) < 6:
                return False

            name = clean_name(tokens[0])
            if not name or name.upper() in {"BOWLING", "O", "M", "R", "W", "ECON", "0S", "4S", "6S", "WD", "NB"}:
                return False

            numeric = tokens[1:]
            try:
                overs = float(numeric[0])
                maidens = int(numeric[1])
                runs = int(numeric[2])
                wickets = int(numeric[3])
                economy = float(numeric[4])
            except Exception:
                return False

            dot_balls = None
            if len(numeric) >= 10:
                try:
                    dot_balls = int(numeric[5])
                except Exception:
                    return False
            elif has_dot_balls_column and len(numeric) >= 6:
                try:
                    dot_balls = int(numeric[5])
                except Exception:
                    dot_balls = None

            if overs < 0 or overs > 4.0:
                return False
            if maidens < 0 or maidens > 4:
                return False
            if runs < 0 or runs > 80:
                return False
            if wickets < 0 or wickets > 5:
                return False
            if dot_balls is not None and (dot_balls < 0 or dot_balls > 24):
                return False

            return _apply_bowling_row(name, bowling_team, overs, maidens, runs, wickets, economy, dot_balls=dot_balls)

        def parse_dot_ball_section(start_idx, end_idx):
            parsed_any = False
            for idx in range(start_idx, end_idx):
                line = lines[idx]
                match_obj = None
                if re.match(r"^Bowling\b", line, flags=re.IGNORECASE):
                    match_obj = re.match(
                        r"^(?P<name>.+?)(?:\s+|\s*)(?P<overs>\d+(?:\.\d+)?)\s+(?P<maidens>\d+)\s+(?P<runs>\d+)\s+(?P<wickets>\d+)\s+(?P<economy>\d+(?:\.\d+)?)\s+(?P<dot_balls>\d+)\s+(?P<fours>\d+)\s+(?P<sixes>\d+)\s+(?P<wd>\d+)\s+(?P<nb>\d+)\s*$",
                        line,
                    )
                    if not match_obj:
                        match_obj = re.match(
                            r"^(?P<name>.+?)(?:\s+|\s*)(?P<overs>\d+(?:\.\d+)?)\s+(?P<maidens>\d+)\s+(?P<runs>\d+)\s+(?P<wickets>\d+)\s+(?P<economy>\d+(?:\.\d+)?)\s+(?P<fours>\d+)\s+(?P<sixes>\d+)\s+(?P<wd>\d+)\s+(?P<nb>\d+)\s*$",
                            line,
                        )
                else:
                    match_obj = re.match(
                        r"^(?P<name>.+?)(?:\s+|\s*)(?P<overs>\d+(?:\.\d+)?)\s+(?P<maidens>\d+)\s+(?P<runs>\d+)\s+(?P<wickets>\d+)\s+(?P<economy>\d+(?:\.\d+)?)\s+(?P<dot_balls>\d+)\s+(?P<fours>\d+)\s+(?P<sixes>\d+)\s+(?P<wd>\d+)\s+(?P<nb>\d+)\s*$",
                        line,
                    )
                    if not match_obj:
                        match_obj = re.match(
                            r"^(?P<name>.+?)(?:\s+|\s*)(?P<overs>\d+(?:\.\d+)?)\s+(?P<maidens>\d+)\s+(?P<runs>\d+)\s+(?P<wickets>\d+)\s+(?P<economy>\d+(?:\.\d+)?)\s+(?P<fours>\d+)\s+(?P<sixes>\d+)\s+(?P<wd>\d+)\s+(?P<nb>\d+)\s*$",
                            line,
                        )

                if not match_obj:
                    continue

                name = clean_name(match_obj.group("name"))
                if not name or name.upper() in {"BOWLING", "O", "M", "R", "W", "ECON", "0S", "4S", "6S", "WD", "NB"}:
                    continue

                pid = self.get_player_id(name, self.team1)
                if not pid:
                    pid = self.get_player_id(name, self.team2)
                if not pid:
                    continue

                player = self.get_or_create_player(pid)
                if not player:
                    continue
                try:
                    dot_balls_group = match_obj.groupdict().get("dot_balls")
                    if dot_balls_group is not None:
                        dot_balls = int(dot_balls_group)
                        if dot_balls > 0:
                            player.dot_balls = dot_balls
                            print(
                                f"[Match {self.match_id}] ESPN dot balls parsed: "
                                f"{player.name} ({player.team or 'unknown'}) = {dot_balls}"
                            )
                            parsed_any = True
                except Exception:
                    continue
            return parsed_any

        direct_parsed = False
        for idx, line in enumerate(lines):
            if not re.match(r"^Bowling\b", line, flags=re.IGNORECASE):
                continue

            section_end = len(lines)
            for next_idx in range(idx + 1, len(lines)):
                if re.fullmatch(r".+?\s+[Ii]nnings", lines[next_idx]):
                    section_end = next_idx
                    break

            header_window = lines[idx : min(idx + 8, section_end)]
            has_dot_balls_column = any(
                re.search(
                    r"\b0\s*[s]\b|\bdot\s+balls?\b",
                    " ".join(str(line).strip().lower().split()),
                    flags=re.IGNORECASE,
                )
                or " 0s " in f" {str(line).strip().lower()} "
                for line in header_window
            )

            section_parsed = False
            for row_idx in range(idx + 1, section_end):
                if _parse_pipe_bowling_row(lines[row_idx], self.team1, has_dot_balls_column):
                    section_parsed = True
                    continue
                if _parse_pipe_bowling_row(lines[row_idx], self.team2, has_dot_balls_column):
                    section_parsed = True
                    continue

            direct_parsed = parse_dot_ball_section(idx, section_end) or section_parsed or direct_parsed

        temp_match = Match(self.match_id, self.team1, self.team2, self.registry, self.match_date)
        temp_parsed = temp_match.parse_espn_scorecard(soup)

        for pid, temp_player in temp_match.players.items():
            player = self.get_or_create_player(pid)
            if not player:
                continue
            if temp_player.team and not player.team:
                player.team = temp_player.team
            player.played = player.played or temp_player.played
            for attr in (
                "runs",
                "balls",
                "fours",
                "sixes",
                "strike_rate",
                "overs",
                "maidens",
                "runs_conceded",
                "wickets",
                "economy",
                "catches",
                "runout_direct",
                "runout_indirect",
                "stumpings",
                "bowled",
                "lbw",
                "dismissal",
                "is_out",
            ):
                current_value = getattr(player, attr, 0)
                temp_value = getattr(temp_player, attr, 0)
                if not current_value and temp_value:
                    setattr(player, attr, temp_value)
            if temp_player.dot_balls > 0 and player.dot_balls <= 0:
                player.dot_balls = temp_player.dot_balls

        return direct_parsed or temp_parsed

    def parse_espn_scorecard(self, soup):
        lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
        valid_teams = {self.team1, self.team2}
        reverse_team_map = {
            short: full
            for full, short in TEAM_MAP.items()
            if len(short) <= 4 and full != short
        }

        def team_variants(team):
            variants = {team.lower()}
            full_name = reverse_team_map.get(team, team)
            variants.add(full_name.lower())
            return variants

        # Reject scorecards whose visible title/header teams do not match this match.
        joined_head = " ".join(lines[:80]).lower()
        if not any(name in joined_head for name in team_variants(self.team1)):
            return False
        if not any(name in joined_head for name in team_variants(self.team2)):
            return False

        def mark_player_played(name, team):
            cleaned = str(name).strip()
            if "(sub)" in cleaned.lower():
                return False
            cleaned = re.sub(r"^\d+\s*[.)-]?\s*", "", cleaned)
            cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", cleaned)
            cleaned = clean_name(cleaned)
            if not cleaned:
                return False
            pid = self.get_player_id(cleaned, team)
            if not pid:
                return False
            player = self.get_or_create_player(pid)
            player.team = team
            player.played = True
            return True

        def mark_players_from_line(line, team):
            found_any = False
            for raw_name in re.split(r",|;|\u2022|\||\s{2,}", line):
                if mark_player_played(raw_name, team):
                    found_any = True
            return found_any

        def mark_team_section_line(line, team):
            normalized_line = " " + clean_name(str(line)).lower() + " "
            found_any = False

            for pid, player_data in self.registry.players.items():
                if player_data.get("Team") != team:
                    continue

                candidate_names = [player_data.get("Name", "")]
                aliases = player_data.get("Aliases", "")
                if aliases:
                    candidate_names.extend(alias.strip() for alias in aliases.split(",") if alias.strip())

                for candidate in candidate_names:
                    normalized_candidate = clean_name(candidate).lower()
                    if normalized_candidate and f" {normalized_candidate} " in normalized_line:
                        player = self.get_or_create_player(pid)
                        player.team = team
                        player.played = True
                        found_any = True
                        break

            if found_any:
                return True

            return mark_players_from_line(line, team)

        # Find innings headers like "Royal Challengers Bengaluru Innings"
        def find_innings_headers():
            headers = []
            seen = set()
            for idx, line in enumerate(lines):
                match_obj = re.fullmatch(r"(.+?)\s+[Ii]nnings", line)
                if not match_obj:
                    continue
                raw_team = match_obj.group(1).strip()
                if re.fullmatch(r"\d+(?:st|nd|rd|th)", raw_team.lower()):
                    continue
                team = clean_team_name(raw_team)
                if team not in valid_teams or team in seen:
                    continue
                next_window = lines[idx + 1: idx + 8]
                if not any(text.upper() in ("BATSMEN", "BATTING") for text in next_window):
                    continue
                seen.add(team)
                headers.append((idx, team))
                if len(headers) == 2:
                    break
            return headers

        def find_between(start, end, targets):
            target_set = {item.upper() for item in targets}
            for idx in range(start, end):
                if lines[idx].upper() in target_set:
                    return idx
            return -1

        def find_prefix_between(start, end, prefix):
            prefix = prefix.lower()
            for idx in range(start, end):
                if lines[idx].lower().startswith(prefix):
                    return idx
            return -1

        def is_int_text(value):
            return bool(re.fullmatch(r"\d+", str(value).strip()))

        def is_float_text(value):
            return bool(re.fullmatch(r"\d+(?:\.\d+)?", str(value).strip()))

        def is_reasonable_batter_values(runs, balls, fours, sixes, strike_rate):
            if runs < 0 or runs > 300:
                return False
            if balls < 0 or balls > 200:
                return False
            if fours < 0 or fours > 40:
                return False
            if sixes < 0 or sixes > 25:
                return False
            if strike_rate < 0 or strike_rate > 400:
                return False
            if balls > 0 and (fours > balls or sixes > balls):
                return False
            if runs >= 0 and (fours * 4 + sixes * 6 > runs + 36):
                return False
            return True

        def get_batter_layout(index, end):
            # 8-column layout (with minutes column)
            if index + 7 < end and (
                is_int_text(lines[index + 2]) and is_int_text(lines[index + 3]) and
                is_int_text(lines[index + 4]) and is_int_text(lines[index + 5]) and
                is_int_text(lines[index + 6]) and is_float_text(lines[index + 7])
            ):
                runs = int(lines[index + 2])
                balls = int(lines[index + 3])
                fours = int(lines[index + 5])
                sixes = int(lines[index + 6])
                strike_rate = float(lines[index + 7])
                if is_reasonable_batter_values(runs, balls, fours, sixes, strike_rate):
                    return {"step": 8, "runs_idx": 2, "balls_idx": 3, "fours_idx": 5, "sixes_idx": 6, "sr_idx": 7}
            # 7-column layout
            if index + 6 < end and (
                is_int_text(lines[index + 2]) and is_int_text(lines[index + 3]) and
                is_int_text(lines[index + 4]) and is_int_text(lines[index + 5]) and
                is_float_text(lines[index + 6])
            ):
                runs = int(lines[index + 2])
                balls = int(lines[index + 3])
                fours = int(lines[index + 4])
                sixes = int(lines[index + 5])
                strike_rate = float(lines[index + 6])
                if is_reasonable_batter_values(runs, balls, fours, sixes, strike_rate):
                    return {"step": 7, "runs_idx": 2, "balls_idx": 3, "fours_idx": 4, "sixes_idx": 5, "sr_idx": 6}
            return None

        def looks_like_batter_row(index, end):
            if index + 6 >= end:
                return False
            name = lines[index]
            dismissal = lines[index + 1]
            if name.upper() in {"BATSMEN", "BATTING", "R", "B", "4S", "6S", "SR", "EXTRAS", "TOTAL", "DID NOT BAT", "BOWLING"}:
                return False
            if dismissal.upper() in {"R", "B", "4S", "6S", "SR"}:
                return False
            return get_batter_layout(index, end) is not None

        def looks_like_bowler_row(index, end):
            if index + 6 >= end:
                return False
            name = lines[index]
            if name.upper() in {"BOWLING", "O", "M", "R", "W", "ECON", "0S", "4S", "6S", "WD", "NB"}:
                return False
            return (
                is_float_text(lines[index + 1]) and is_int_text(lines[index + 2]) and
                is_int_text(lines[index + 3]) and is_int_text(lines[index + 4]) and
                    is_float_text(lines[index + 5]) and is_int_text(lines[index + 6])
            )

        def parse_compact_bowling_row(line, bowling_team):
            normalized = " ".join(str(line).strip().split())
            compact_match = re.match(
                r"^(?P<name>.+?)\s+(?P<overs>\d+(?:\.\d+)?)\s+(?P<maidens>\d+)\s+(?P<runs>\d+)\s+(?P<wickets>\d+)\s+(?P<economy>\d+(?:\.\d+)?)\s+(?P<dot_balls>\d+)\s+(?P<fours>\d+)\s+(?P<sixes>\d+)\s+(?P<wd>\d+)\s+(?P<nb>\d+)\s*$",
                normalized,
            )
            if not compact_match:
                return False

            try:
                name = clean_name(compact_match.group("name"))
                overs = float(compact_match.group("overs"))
                maidens = int(compact_match.group("maidens"))
                runs = int(compact_match.group("runs"))
                wickets = int(compact_match.group("wickets"))
                economy = float(compact_match.group("economy"))
                dot_balls = int(compact_match.group("dot_balls"))
            except Exception:
                return False

            if not name or name.upper() in {"BOWLING", "O", "M", "R", "W", "ECON", "0S", "4S", "6S", "WD", "NB"}:
                return False
            if overs < 0 or overs > 4.0:
                return False
            if maidens < 0 or maidens > 4:
                return False
            if runs < 0 or runs > 80:
                return False
            if wickets < 0 or wickets > 5:
                return False
            if dot_balls < 0 or dot_balls > 24:
                return False

            pid = self.get_player_id(name, bowling_team)
            if not pid:
                return False

            player = self.get_or_create_player(pid)
            if not player:
                return False
            player.team = bowling_team
            player.played = True
            player.overs = overs
            player.maidens = maidens
            player.runs_conceded = runs
            player.wickets = wickets
            player.economy = economy
            if player.dot_balls <= 0:
                player.dot_balls = dot_balls
            return True

        def is_reasonable_bowling_row(index, has_dot_balls_column):
            try:
                overs = float(lines[index + 1])
                maidens = int(lines[index + 2])
                runs = int(lines[index + 3])
                wickets = int(lines[index + 4])
                trailing_value = int(lines[index + 6])
            except Exception:
                return False

            # Defensive bounds for T20 bowling; reject obviously corrupted rows.
            if overs < 0 or overs > 4.0:
                return False
            if maidens < 0 or maidens > 4:
                return False
            if runs < 0 or runs > 80:
                return False
            if wickets < 0 or wickets > 5:
                return False
            if has_dot_balls_column and (trailing_value < 0 or trailing_value > 24):
                return False

            return True

        def get_bowling_dot_balls(index, has_dot_balls_column):
            if not has_dot_balls_column:
                return None

            # ESPN scorecards usually place dot balls immediately after economy,
            # but some layouts can shift the visible cells slightly. Scan a small
            # forward window and take the first plausible dot-ball integer.
            for offset in range(6, min(11, len(lines) - index)):
                candidate = lines[index + offset]
                if not is_int_text(candidate):
                    continue
                trailing_value = int(candidate)
                if 0 <= trailing_value <= 24:
                    return trailing_value
            return None

        innings_headers = find_innings_headers()
        if not innings_headers:
            return False

        for header_pos, batting_team in innings_headers:
            next_header_positions = [pos for pos, _ in innings_headers if pos > header_pos]
            section_end = next_header_positions[0] if next_header_positions else len(lines)
            bowling_team = self.team2 if batting_team == self.team1 else self.team1

            for stop_marker in ("Match Details", "Match Notes", "Match Coverage", "All Match News"):
                stop_idx = find_between(header_pos, section_end, (stop_marker,))
                if stop_idx != -1:
                    section_end = stop_idx
                    break

            batting_header = find_between(header_pos, section_end, ("BATSMEN", "BATTING"))
            extras_idx = find_between(header_pos, section_end, ("Extras", "EXTRAS"))

            # Parse batters
            if batting_header != -1 and extras_idx != -1:
                idx = batting_header + 1
                while idx < extras_idx:
                    if looks_like_batter_row(idx, extras_idx):
                        layout = get_batter_layout(idx, extras_idx)
                        name = clean_name(lines[idx])
                        dismissal = lines[idx + 1]
                        pid = self.get_player_id(name, batting_team)
                        if not pid:
                            idx += 1
                            continue
                        player = self.get_or_create_player(pid)
                        player.team = batting_team
                        player.played = True
                        player.runs = int(lines[idx + layout["runs_idx"]])
                        player.balls = int(lines[idx + layout["balls_idx"]])
                        player.fours = int(lines[idx + layout["fours_idx"]])
                        player.sixes = int(lines[idx + layout["sixes_idx"]])
                        if player.balls > 0:
                            player.strike_rate = round((player.runs / player.balls) * 100, 2)
                        player.apply_dismissal(dismissal, self, bowling_team)
                        idx += layout["step"]
                        continue
                    idx += 1

            # Parse DNB
            dnb_idx = find_between(header_pos, section_end, ("Did not bat", "Yet to bat", "Yet To Bat"))
            bowling_idx = find_prefix_between(header_pos, section_end, "Bowling")
            fow_idx = find_prefix_between(header_pos, section_end, "fall of wickets")
            dnb_end = min(idx for idx in (fow_idx, bowling_idx, section_end) if idx != -1)

            if dnb_idx != -1:
                for idx in range(dnb_idx + 1, dnb_end):
                    line = lines[idx]
                    if line == ":":
                        continue
                    mark_players_from_line(line, batting_team)

            # Parse bowlers
            if bowling_idx != -1:
                bowling_header_lines = lines[bowling_idx: min(bowling_idx + 8, section_end)]

                def is_dot_ball_header(line):
                    normalized = " ".join(str(line).strip().lower().split())
                    return bool(
                        re.search(r"\b0\s*[s]\b|\bdot\s+balls?\b", normalized, flags=re.IGNORECASE)
                        or normalized in {"0s", "0 s"}
                    )

                has_dot_balls_column = any(
                    is_dot_ball_header(line)
                    for line in bowling_header_lines
                )
                idx = bowling_idx + 1
                while idx < section_end:
                    current_line = lines[idx]
                    if parse_compact_bowling_row(current_line, bowling_team):
                        idx += 1
                        continue
                    if looks_like_bowler_row(idx, section_end):
                        if not is_reasonable_bowling_row(idx, has_dot_balls_column):
                            idx += 1
                            continue
                        name = clean_name(lines[idx])
                        pid = self.get_player_id(name, bowling_team)
                        if not pid:
                            idx += 1
                            continue
                        player = self.get_or_create_player(pid)
                        player.team = bowling_team
                        player.played = True
                        player.overs = float(lines[idx + 1])
                        player.maidens = int(lines[idx + 2])
                        player.runs_conceded = int(lines[idx + 3])
                        player.wickets = int(lines[idx + 4])
                        dot_balls = get_bowling_dot_balls(idx, has_dot_balls_column)
                        if dot_balls is None:
                            # Some ESPN layouts omit the 0s header or insert a
                            # stray numeric cell before dot balls. Scan the
                            # small trailing window and take the first plausible
                            # dot-ball value.
                            for offset in range(6, min(11, section_end - idx)):
                                candidate = lines[idx + offset]
                                if not is_int_text(candidate):
                                    continue
                                trailing_value = int(candidate)
                                if 0 <= trailing_value <= 24:
                                    dot_balls = trailing_value
                                    break
                        if dot_balls is not None and player.dot_balls <= 0:
                            player.dot_balls = dot_balls
                        if player.overs > 0:
                            player.economy = round(player.runs_conceded / player.overs, 2)
                        idx += 7
                        continue
                    line = lines[idx]
                    inline_match = None
                    if has_dot_balls_column:
                        inline_match = re.match(
                            r"^(?P<name>.+?)(?:\s+|\s*)(?P<overs>\d+(?:\.\d+)?)\s+(?P<maidens>\d+)\s+(?P<runs>\d+)\s+(?P<wickets>\d+)\s+(?P<economy>\d+(?:\.\d+)?)\s+(?P<dot_balls>\d+)\s+(?P<fours>\d+)\s+(?P<sixes>\d+)\s+(?P<wd>\d+)\s+(?P<nb>\d+)\s*$",
                            line,
                        )
                    if not inline_match:
                        inline_match = re.match(
                            r"^(?P<name>.+?)(?:\s+|\s*)(?P<overs>\d+(?:\.\d+)?)\s+(?P<maidens>\d+)\s+(?P<runs>\d+)\s+(?P<wickets>\d+)\s+(?P<economy>\d+(?:\.\d+)?)\s+(?P<fours>\d+)\s+(?P<sixes>\d+)\s+(?P<wd>\d+)\s+(?P<nb>\d+)\s*$",
                            line,
                        )
                    if inline_match:
                        name = clean_name(inline_match.group("name"))
                        if name and name.upper() not in {
                            "BOWLING",
                            "O",
                            "M",
                            "R",
                            "W",
                            "ECON",
                            "0S",
                            "4S",
                            "6S",
                            "WD",
                            "NB",
                        }:
                            pid = self.get_player_id(name, bowling_team)
                            if pid:
                                player = self.get_or_create_player(pid)
                                player.team = bowling_team
                                player.played = True
                                try:
                                    player.overs = float(inline_match.group("overs"))
                                    player.maidens = int(inline_match.group("maidens"))
                                    player.runs_conceded = int(inline_match.group("runs"))
                                    player.wickets = int(inline_match.group("wickets"))
                                    player.economy = float(inline_match.group("economy"))
                                    dot_balls_group = inline_match.groupdict().get("dot_balls")
                                    if dot_balls_group is not None and player.dot_balls <= 0:
                                        player.dot_balls = int(dot_balls_group)
                                except Exception:
                                    pass
                    idx += 1

        for team in (self.team1, self.team2):
            team_markers = {
                f"{team} team".lower(),
                f"{reverse_team_map.get(team, team)} team".lower(),
            }
            for idx, line in enumerate(lines):
                normalized_line = " ".join(line.lower().split())
                if not any(marker and marker in normalized_line for marker in team_markers):
                    continue

                for team_line in lines[idx + 1:idx + 50]:
                    upper_line = team_line.upper()
                    if upper_line in {"BATSMEN", "BATTING", "BOWLING", "EXTRAS", "TOTAL"}:
                        continue
                    if upper_line.endswith(" INNINGS") or upper_line.startswith("FALL OF WICKETS"):
                        break
                    mark_team_section_line(team_line, team)

        return True

    def parse_legacy_scorecard(self, soup: BeautifulSoup):
        self.players = {}

        def get_table_rows(table):
            return [row for row in table.find_all("tr") if row.find_parent("table") == table]

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
            print("Teams not found in scorecard")
            return

        team1_clean = team_names[0]
        team2_clean = team_names[1]

        # --- BATTING ---
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

        for i, table in enumerate(batting_tables[:2]):
            batting_team = team1_clean if i == 0 else team2_clean
            bowling_team = team2_clean if batting_team == team1_clean else team1_clean
            innings_started = False

            for r in get_table_rows(table):
                tds = get_row_cells(r, ("td",))
                cols = [c.get_text(" ", strip=True) for c in tds]

                if len(cols) < 7:
                    continue

                first = cols[0].upper()
                if first == "BATTING":
                    if innings_started and batting_team == team1_clean:
                        batting_team = team2_clean
                        bowling_team = team1_clean
                    continue

                if first in ("BOWLING", "TOTAL", "EXTRAS", "DNB", "SR", "R"):
                    continue

                first_td = tds[0] if tds else None
                if not first_td or not first_td.find("a"):
                    continue

                if not all(is_int_text(cols[idx]) for idx in (2, 3, 4, 5)):
                    continue

                name = clean_name(first_td.find("a").get_text(" ", strip=True))
                pid = self.get_player_id(name, batting_team)
                if not pid:
                    continue

                player = self.get_or_create_player(pid)
                innings_started = True

                player.team = batting_team
                player.played = True
                player.runs = int(cols[2])
                player.balls = int(cols[3])
                player.fours = int(cols[4])
                player.sixes = int(cols[5])

                if player.balls > 0:
                    player.strike_rate = round((player.runs / player.balls) * 100, 2)

                player.apply_dismissal(cols[1], self, bowling_team)

            # Did Not Bat
            current_batting_team = team1_clean if i == 0 else team2_clean
            for td in table.find_all("td"):
                td_text = td.get_text(" ", strip=True)
                if "Did Not Bat" not in td_text:
                    continue
                next_td = td.find_next_sibling("td")
                if not next_td:
                    continue
                for p in next_td.find_all("a"):
                    name = clean_name(p.get_text(" ", strip=True))
                    pid = self.get_player_id(name, current_batting_team)
                    if not pid:
                        continue
                    player = self.get_or_create_player(pid)
                    player.played = True
                    player.team = current_batting_team

        # --- BOWLING ---
        bowling_tables = soup.find_all(class_="ScorecardBowling")

        for i, table in enumerate(bowling_tables[:2]):
            bowling_team = team2_clean if i == 0 else team1_clean

            for r in get_table_rows(table)[1:]:
                tds = get_row_cells(r, ("td",))
                cols = [c.get_text(" ", strip=True) for c in tds]

                if len(cols) < 5:
                    continue

                first = cols[0].upper()
                if first in ("BOWLING", "TOTAL", "O", "M", "R", "W", "ER", "% WICKETS"):
                    continue

                first_td = tds[0] if tds else None
                if not first_td or not first_td.find("a"):
                    continue

                if not is_float_text(cols[1]) or not all(is_int_text(cols[idx]) for idx in (2, 3, 4)):
                    continue

                name = clean_name(first_td.get_text())
                pid = self.get_player_id(name, bowling_team)
                if not pid:
                    continue

                player = self.get_or_create_player(pid)
                player.team = bowling_team
                player.played = True
                player.overs = float(cols[1])
                player.maidens = int(cols[2])
                player.runs_conceded = int(cols[3])
                player.wickets = int(cols[4])

                if player.overs > 0:
                    player.economy = round(player.runs_conceded / player.overs, 2)

        print(f"Total players parsed: {len(self.players)}")
