import re


def is_batting_role(role):
    return role in ("Batter", "Wicketkeeper", "AllRounder")


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
        self.dot_balls = 0
        self.bowled = 0
        self.lbw = 0
        self.economy = 0.0

        # Fielding
        self.catches = 0
        self.runout_direct = 0
        self.runout_indirect = 0
        self.stumpings = 0

        self.played = False
        self.points = 0
        self.role = None

    # --- Dismissal parser ---

    def apply_dismissal(self, dismissal_text, match, bowling_team=None):
        self.dismissal = " ".join(str(dismissal_text).strip().split())
        dismissal_lower = self.dismissal.lower()

        if dismissal_lower in {"", "not out", "batting"}:
            self.is_out = False
            return

        if "(sub" in dismissal_lower or dismissal_lower.startswith("sub "):
            self.is_out = True
            return

        self.is_out = True

        def get_player(name):
            normalized_name = str(name).lower()
            if "(sub)" in normalized_name or normalized_name.startswith("sub ") or normalized_name.startswith("sub ("):
                return None
            if bowling_team:
                return match.get_player_by_team(name, bowling_team)
            return match.get_player_by_name(name)

        # LBW
        if re.match(r"^lbw\s+b\s+", self.dismissal, flags=re.IGNORECASE):
            m = re.search(r"^lbw\s+b\s+(.+)$", self.dismissal, flags=re.IGNORECASE)
            if m:
                bowler = get_player(m.group(1))
                if bowler:
                    bowler.wickets += 1
                    bowler.lbw += 1
            return

        # Caught
        if re.match(r"^c\s+.+\s+b\s+", self.dismissal, flags=re.IGNORECASE):
            m = re.search(r"^c\s+(.+?)\s+b\s+(.+)$", self.dismissal, flags=re.IGNORECASE)
            if m:
                fielder_name = m.group(1).strip()
                bowler = get_player(m.group(2))
                # "c & b Bowler" means caught-and-bowled by the bowler.
                if fielder_name.lower() in {"&", "&amp;", "and"}:
                    fielder = bowler
                else:
                    fielder = get_player(fielder_name)
                if fielder:
                    fielder.catches += 1
                if bowler:
                    bowler.wickets += 1
            return

        # Bowled
        if re.match(r"^b\s+", self.dismissal, flags=re.IGNORECASE):
            bowler = get_player(re.sub(r"^b\s+", "", self.dismissal, flags=re.IGNORECASE).strip())
            if bowler:
                bowler.wickets += 1
                bowler.bowled += 1
            return

        # Stumping
        if re.match(r"^st\s+.+\s+b\s+", self.dismissal, flags=re.IGNORECASE):
            m = re.search(r"^st\s+(.+?)\s+b\s+(.+)$", self.dismissal, flags=re.IGNORECASE)
            if m:
                fielder = get_player(m.group(1))
                bowler = get_player(m.group(2))
                if fielder:
                    fielder.stumpings += 1
                    fielder.runout_direct += 1
                if bowler:
                    bowler.wickets += 1
            return

        # Run out
        if "run out" in dismissal_lower:
            m = re.search(r"\((.*?)\)", self.dismissal)
            if m:
                fielders = [f.strip() for f in m.group(1).split("/")]
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

    # --- Points engine ---

    def calculate_player_points(self, role: str):
        points = 0
        self.role = role

        # Playing
        if self.played:
            points += 4

        # Batting: runs
        points += self.runs

        # Boundaries
        points += self.fours * 4
        points += self.sixes * 6

        # Milestones
        if self.runs >= 100:
            points += 16
        elif self.runs >= 75:
            points += 12
        elif self.runs >= 50:
            points += 8
        elif self.runs >= 30:
            points += 4

        # Duck
        if self.runs == 0 and self.is_out and is_batting_role(role):
            points -= 2

        # Strike rate (min 10 balls, batting roles only)
        if self.balls >= 10 and is_batting_role(role):
            sr = self.strike_rate
            if sr > 170:
                points += 6
            elif sr > 150:
                points += 4
            elif sr >= 130:
                points += 2
            elif sr <= 50:
                points -= 6
            elif sr < 60:
                points -= 4
            elif sr <= 70:
                points -= 2

        # Bowling: wickets
        points += self.wickets * 30
        points += (self.bowled + self.lbw) * 8

        # Wicket haul bonus
        if self.wickets >= 5:
            points += 16
        elif self.wickets == 4:
            points += 8
        elif self.wickets == 3:
            points += 4

        # Maidens
        points += self.maidens * 12

        # Dot balls
        points += self.dot_balls

        # Economy (min 2 overs)
        if self.overs >= 2:
            eco = self.economy
            if eco < 5:
                points += 6
            elif eco < 6:
                points += 4
            elif eco <= 7:
                points += 2
            elif eco > 12:
                points -= 6
            elif eco > 11:
                points -= 4
            elif eco >= 10:
                points -= 2

        # Fielding
        points += self.catches * 8
        if self.catches >= 3:
            points += 4
        points += self.stumpings * 12
        points += self.runout_direct * 12
        points += self.runout_indirect * 6

        self.points = points
        return points

    def get_points_breakdown(self):
        """Return detailed breakdown of how points were calculated."""
        b = []
        role = self.role or ""

        if self.played:
            b.append({"label": "Playing XI", "points": 4})

        if self.runs > 0:
            b.append({"label": f"Runs ({self.runs})", "points": self.runs})
        if self.fours > 0:
            b.append({"label": f"Fours ({self.fours})", "points": self.fours * 4})
        if self.sixes > 0:
            b.append({"label": f"Sixes ({self.sixes})", "points": self.sixes * 6})

        if self.runs >= 100:
            b.append({"label": "Century bonus", "points": 16})
        elif self.runs >= 75:
            b.append({"label": "75 runs bonus", "points": 12})
        elif self.runs >= 50:
            b.append({"label": "Half-century bonus", "points": 8})
        elif self.runs >= 30:
            b.append({"label": "30 runs bonus", "points": 4})

        if self.runs == 0 and self.is_out and is_batting_role(role):
            b.append({"label": "Duck", "points": -2})

        if self.balls >= 10 and is_batting_role(role):
            sr = self.strike_rate
            if sr > 170:
                b.append({"label": f"SR {sr} (>170)", "points": 6})
            elif sr > 150:
                b.append({"label": f"SR {sr} (>150)", "points": 4})
            elif sr >= 130:
                b.append({"label": f"SR {sr} (>=130)", "points": 2})
            elif sr <= 50:
                b.append({"label": f"SR {sr} (<=50)", "points": -6})
            elif sr < 60:
                b.append({"label": f"SR {sr} (<60)", "points": -4})
            elif sr <= 70:
                b.append({"label": f"SR {sr} (<=70)", "points": -2})

        if self.wickets > 0:
            b.append({"label": f"Wickets ({self.wickets})", "points": self.wickets * 30})
        bowled_lbw_bonus_count = self.bowled + self.lbw
        if bowled_lbw_bonus_count > 0:
            b.append({"label": f"Bowled/LBW ({bowled_lbw_bonus_count})", "points": bowled_lbw_bonus_count * 8})
        if self.wickets >= 5:
            b.append({"label": "5-wicket haul", "points": 16})
        elif self.wickets == 4:
            b.append({"label": "4-wicket haul", "points": 8})
        elif self.wickets == 3:
            b.append({"label": "3-wicket haul", "points": 4})

        if self.maidens > 0:
            b.append({"label": f"Maidens ({self.maidens})", "points": self.maidens * 12})
        if self.dot_balls > 0:
            b.append({"label": f"Dot balls ({self.dot_balls})", "points": self.dot_balls})

        if self.overs >= 2:
            eco = self.economy
            if eco < 5:
                b.append({"label": f"Economy {eco} (<5)", "points": 6})
            elif eco < 6:
                b.append({"label": f"Economy {eco} (<6)", "points": 4})
            elif eco <= 7:
                b.append({"label": f"Economy {eco} (<=7)", "points": 2})
            elif eco > 12:
                b.append({"label": f"Economy {eco} (>12)", "points": -6})
            elif eco > 11:
                b.append({"label": f"Economy {eco} (>11)", "points": -4})
            elif eco >= 10:
                b.append({"label": f"Economy {eco} (>=10)", "points": -2})

        if self.catches > 0:
            b.append({"label": f"Catches ({self.catches})", "points": self.catches * 8})
        if self.catches >= 3:
            b.append({"label": "3+ catches bonus", "points": 4})
        if self.stumpings > 0:
            b.append({"label": f"Stumpings ({self.stumpings})", "points": self.stumpings * 12})
        if self.runout_direct > 0:
            b.append({"label": f"Direct run out ({self.runout_direct})", "points": self.runout_direct * 12})
        if self.runout_indirect > 0:
            b.append({"label": f"Indirect run out ({self.runout_indirect})", "points": self.runout_indirect * 6})

        return b
