export type User = {
  id: number;
  firebase_uid: string;
  email: string;
  name: string;
  mobile?: string;
  role: 'user' | 'admin';
  is_active: boolean;
};

export type VenueStats = {
  venue: string;
  city: string;
  matches: number;
  avg_first_innings: number;
  bat_first_win_pct: number;
  chase_win_pct: number;
  pitch_type: string;
};

export type TossInfo = {
  announced: boolean;
  team?: string | null;
  decision?: 'bat' | 'bowl' | string | null;
  text?: string;
  url?: string | null;
};

export type Match = {
  id: number;
  team1: string;
  team2: string;
  match_date: string;
  match_time: string;
  toss_time?: string | null;
  status: 'future' | 'live' | 'completed' | 'nr';
  locked: boolean;
  venue?: VenueStats | null;
  toss?: TossInfo | null;
  current_rank?: number | null;
};

export type Player = {
  id: number;
  name: string;
  team: string;
  role: string;
  aliases: string;
  total_points?: number;
  matches_played?: number;
  avg_points?: number;
  last_match_points?: number | null;
  is_playing_xi?: boolean | null;
  is_substitute?: boolean | null;
  availability_status?: 'available' | 'substitute' | 'unavailable' | null;
  availability_order?: number | null;
  recent_history?: Array<{
    match_id: number;
    opponent?: string | null;
    points?: number | null;
    did_not_play: boolean;
  }>;
};

export type PlayingXiInfo = {
  announced: boolean;
  url?: string | null;
  playingCount?: number;
  substituteCount?: number;
  lineup_window_open?: boolean;
};

export type TeamSelection = {
  player_id: number;
  player_name: string;
  team: string;
  role: string;
  is_captain: boolean;
  is_vice_captain: boolean;
};

export type TeamBackup = {
  backup_order: number;
  backup_player_id: number;
  backup_player_name: string;
  backup_team: string;
  backup_role: string;
  replaced_player_id?: number | null;
  replaced_player_name?: string | null;
};

export type PlayerScore = {
  name: string;
  team: string;
  role: string;
  played: boolean;
  is_out: boolean;
  runs: number;
  balls: number;
  fours: number;
  sixes: number;
  strike_rate: number;
  overs: number;
  maidens: number;
  runs_conceded: number;
  wickets: number;
  dot_balls: number;
  bowled: number;
  lbw: number;
  economy: number;
  catches: number;
  runout_direct: number;
  runout_indirect: number;
  stumpings: number;
  points: number;
  owners?: Array<{
    id: number;
    name: string;
    tag?: string;
  }>;
};

export type ContestantScore = {
  id: number;
  name: string;
  points: number;
  rank?: number;
};

export type LeaderboardEntry = {
  rank: number;
  name: string;
  user_id: number;
  points: number;
  gold: number;
  silver: number;
  bronze: number;
  balance: number;
};

export type PointsTableEntry = {
  user_id: number;
  name: string;
  match_id: number;
  points: number;
  last_updated: string;
  adjusted?: boolean;
  participated?: boolean;
};

export type AdminMatchWithTeamCount = {
  id: number;
  team1: string;
  team2: string;
  match_date: string;
  match_time: string;
  team_count: number;
};

export type AdminTeamPlayer = {
  player_id: number;
  player_name: string;
  team: string;
  role: string;
  is_captain: boolean;
  is_vice_captain: boolean;
};

export type AdminUserTeam = {
  user_id: number;
  user_name: string;
  user_email?: string;
  user_mobile?: string;
  players: AdminTeamPlayer[];
  team_counts: Record<string, number>;
  captain_name?: string | null;
  vice_captain_name?: string | null;
};
