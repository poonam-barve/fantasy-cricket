class PlayerRegistry:
    def __init__(self, players_data):
        self.players = {}   # pid -> full row
        self.lookup = {}    # (team, normalized full name/alias) -> pid
        self.first_name_lookup = {}  # (team, first_name) -> set[pids]
        self.last_name_lookup = {}   # (team, last_name) -> set[pids]
        self.build(players_data)

    def normalize(self, name):
        return " ".join(name.lower().replace(".", "").split())

    def _extract_initials_and_surname(self, normalized_name):
        parts = normalized_name.split()
        if len(parts) < 2:
            return [], None

        surname = parts[-1]
        initials = []

        for part in parts[:-1]:
            compact = part.replace(" ", "")
            if not compact:
                continue

            # Support both "RG Sharma" and "R G Sharma" style abbreviations.
            if len(compact) > 1 and compact.isalpha():
                initials.extend(list(compact))
            else:
                initials.append(compact[0])

        return [initial.lower() for initial in initials if initial], surname

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
                # Keep the first exact key we see so generic aliases like
                # "Sharma" do not overwrite a more useful earlier mapping.
                if (team, normalized) not in self.lookup:
                    self.lookup[(team, normalized)] = pid

                parts = normalized.split()
                if len(parts) > 1:
                    self.first_name_lookup.setdefault((team, parts[0]), set()).add(pid)
                    self.last_name_lookup.setdefault((team, parts[-1]), set()).add(pid)

    def get_player_id(self, name, team):
        normalized_name = self.normalize(name)

        # Try whole name
        if (team, normalized_name) in self.lookup:
            return self.lookup[(team, normalized_name)]

        candidates = self.get_player_candidates(name, team)
        if len(candidates) == 1:
            return next(iter(candidates))

        print(f"Player mapping not found: '{name}' (team: {team})")
        return None

    def get_player_candidates(self, name, team):
        normalized_name = self.normalize(name)
        candidates = set()

        # Try whole name
        if (team, normalized_name) in self.lookup:
            candidates.add(self.lookup[(team, normalized_name)])

        parts = normalized_name.split()
        if len(parts) > 1:
            first_name_matches = self.first_name_lookup.get((team, parts[0]), set())
            last_name_matches = self.last_name_lookup.get((team, parts[-1]), set())
            combined_matches = first_name_matches & last_name_matches
            candidates.update(combined_matches)
        elif len(parts) == 1:
            first_name_matches = self.first_name_lookup.get((team, parts[0]), set())
            candidates.update(first_name_matches)

            last_name_matches = self.last_name_lookup.get((team, parts[0]), set())
            candidates.update(last_name_matches)

        initials, surname = self._extract_initials_and_surname(normalized_name)
        if surname:
            surname_matches = self.last_name_lookup.get((team, surname), set())
            candidates.update(surname_matches)

            if initials:
                first_initial = initials[0]
                matching_candidates = set()
                for pid in surname_matches:
                    player_name = self.normalize(self.players.get(pid, {}).get("Name", ""))
                    if not player_name:
                        continue
                    player_parts = player_name.split()
                    if player_parts and player_parts[0].startswith(first_initial):
                        matching_candidates.add(pid)
                candidates.update(matching_candidates)

        return candidates
