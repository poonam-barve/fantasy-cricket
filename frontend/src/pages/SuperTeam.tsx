import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import client from '../api/client';
import { useToast } from '../components/Toast';
import type { Player } from '../types';
import { getTeamTheme } from '../utils/teamTheme';

type Role = 'Wicketkeeper' | 'Batter' | 'AllRounder' | 'Bowler';
type PlayerView = Role | 'Squad';
type SuperTab = 'live' | 'myteam' | 'compare';
type SuperContext = {
  visible: boolean;
  enabled: boolean;
  locked: boolean;
  can_edit?: boolean;
  substitution_open?: boolean;
  substitution_finalized?: boolean;
  substitution_phase?: number;
  public_visible?: boolean;
  bonus_visible: boolean;
  teams: string[];
  substitution_teams?: string[];
  message: string;
  matches?: Record<string, { Team1: string; Team2: string; Date: string; Time: string; Status?: string | null }>;
};
type Contestant = { user_id: number; name: string; last_team_updated: string | null };
type MissingUser = { id: number; name: string };
type Penalty = { total: number; new_player_count: number; new_player_penalty: number; captain_changed: boolean; captain_penalty: number; vice_captain_changed: boolean; vice_captain_penalty: number; new_player_ids?: number[]; phase1?: Penalty; phase2?: Penalty };
type Standing = { user_id: number; name: string; points: number; gross_points?: number; penalty?: Penalty; rank: number; match_points: Record<string, number> };
type SuperBreakdownPlayer = { player_id: number; name: string; team: string; role: Role; base_points?: number; multiplier?: number; tag?: string; points: number; removed?: boolean };
type SuperBreakdownMatch = { match_id: number; points: number; players: SuperBreakdownPlayer[] };
type SuperUserBreakdown = Standing & { matches: SuperBreakdownMatch[] };
type AggregatedBreakdownPlayer = SuperBreakdownPlayer & { match_points: Record<string, number>; substituted: boolean };
type SuperPlayerPoints = {
  player_id: number;
  name: string;
  team: string;
  role: Role;
  points: number;
  match_points: Record<string, number>;
  match_breakdowns?: Record<string, { label: string; points: number }[]>;
};
type MyTeamPlayer = { player_id: number | string; is_captain?: boolean; is_vice_captain?: boolean };

const roles: Role[] = ['Wicketkeeper', 'Batter', 'AllRounder', 'Bowler'];
const requiredRoles: Role[] = ['Wicketkeeper', 'Batter', 'AllRounder'];
const MY_TEAM_TAB = 'My Team';
const SUPER_TEAM_SIZE = 12;
const MIN_BOWLERS = 4;
const SUPER_TABS: Array<{ key: SuperTab; label: string }> = [
  { key: 'live', label: 'Live' },
  { key: 'myteam', label: 'My Team' },
  { key: 'compare', label: 'Compare' },
];
const formatPoints = (value: number | null | undefined) => {
  if (value == null || Number.isNaN(value)) return '-';
  const rounded = Math.round(value * 2) / 2;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
};

function statText(player: Player) {
  const bits = [
    `${player.total_points || 0} pts`,
    `${player.matches_played || 0} matches`,
    `${player.avg_points || 0} avg`,
  ];
  if (player.last_match_points != null) bits.push(`${player.last_match_points} last`);
  return bits.join(' | ');
}

function statusLabel(context: SuperContext) {
  if (!context.enabled) return { text: 'Upcoming', color: 'bg-blue-500/20 text-blue-400 border-blue-500/30' };
  if (context.bonus_visible) return { text: 'Completed', color: 'bg-white/10 text-white/50 border-white/20' };
  if (context.substitution_open) return { text: 'Subs Open', color: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30' };
  if (context.locked) return { text: 'Live', color: 'bg-green-500/20 text-green-400 border-green-500/30' };
  return { text: 'Open', color: 'bg-amber-500/20 text-amber-400 border-amber-500/30' };
}

function matchProgressTone(status: string | null | undefined) {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'completed') return 'bg-green-500';
  if (normalized === 'live') return 'bg-green-500 animate-pulse';
  return 'bg-white/10';
}

function apiErrorDetail(error: unknown, fallback: string) {
  const response = (error as { response?: { data?: { detail?: unknown } } } | null)?.response;
  return typeof response?.data?.detail === 'string' ? response.data.detail : fallback;
}

export default function SuperTeamPage() {
  const { toast } = useToast();
  const [context, setContext] = useState<SuperContext | null>(null);
  const [playersByRole, setPlayersByRole] = useState<Record<Role, Player[]>>({
    Wicketkeeper: [],
    Batter: [],
    AllRounder: [],
    Bowler: [],
  });
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [captain, setCaptain] = useState<number | null>(null);
  const [viceCaptain, setViceCaptain] = useState<number | null>(null);
  const [myPenalty, setMyPenalty] = useState<Penalty | null>(null);
  const [projectedPenalty, setProjectedPenalty] = useState<Penalty | null>(null);
  const [standings, setStandings] = useState<Standing[]>([]);
  const [myUserId, setMyUserId] = useState<number | null>(null);
  const [userBreakdowns, setUserBreakdowns] = useState<SuperUserBreakdown[]>([]);
  const [playerPointRows, setPlayerPointRows] = useState<SuperPlayerPoints[]>([]);
  const [selectedBreakdownUserId, setSelectedBreakdownUserId] = useState<number | null>(null);
  const [activePlayerStatsMatchId, setActivePlayerStatsMatchId] = useState(71);
  const [tab, setTab] = useState<SuperTab>('live');
  const [contestants, setContestants] = useState<Contestant[]>([]);
  const [missingUsers, setMissingUsers] = useState<MissingUser[]>([]);
  const [contestantsTab, setContestantsTab] = useState<'playing' | 'missing'>('playing');
  const [activeTeam, setActiveTeam] = useState<string | null>(null);
  const [activePlayerView, setActivePlayerView] = useState<PlayerView>('Squad');
  const [expandedStatsPlayerId, setExpandedStatsPlayerId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [showContestants, setShowContestants] = useState(false);
  const [showPlayerSearch, setShowPlayerSearch] = useState(false);
  const [playerSearch, setPlayerSearch] = useState('');
  const [openHistoryPlayerId, setOpenHistoryPlayerId] = useState<number | null>(null);
  const superTeamRules = [
    'Super Team is a one-team playoff squad.',
    'Pick 12 players from the four playoff teams',
    'You must select at least 1 Wicketkeeper, 1 Batter, 1 AllRounder and 4 Bowlers. Bowlers can be from any team.',
    'Captain scores 1.5x points. Vice-Captain scores 1.25x points rounded up to the next 0.5.',
    'Initial team selection locks at Qualifier 1 toss.',
    'Two substitution windows open before Qualifier 2 and Final tosses.',
    'Substitution penalties are role based and reset for each window.',
    'Window 1: new WK/BAT/AR -80, new Bowler -60. Window 2: new WK/BAT/AR -100, new Bowler -80. Captain changes cost half, Vice-Captain changes cost one-fourth points penalty.',
    'After Final, rank 1 gets +1000, rank 2 gets +600, and rank 3 gets +300 leaderboard bonus.',
  ];

  const load = useCallback(async () => {
    try {
      const res = await client.get('/api/super-team');
      setContext(res.data.context);
      setMyUserId(res.data.my_user_id || null);
      setPlayersByRole(res.data.players || {});
      setStandings(res.data.standings || []);
      setUserBreakdowns(res.data.details?.user_breakdowns || []);
      setPlayerPointRows(res.data.details?.player_points || []);
      setContestants(res.data.contestants || []);
      setMissingUsers(res.data.missing_users || []);
      const myTeamPlayers = (res.data.my_team?.players || []) as MyTeamPlayer[];
      const ids = myTeamPlayers.map((player) => Number(player.player_id));
      setSelected(new Set(ids));
      const captainPlayer = myTeamPlayers.find((player) => player.is_captain);
      const viceCaptainPlayer = myTeamPlayers.find((player) => player.is_vice_captain);
      setCaptain(captainPlayer ? Number(captainPlayer.player_id) : res.data.my_team?.captain ? Number(res.data.my_team.captain) : null);
      setViceCaptain(viceCaptainPlayer ? Number(viceCaptainPlayer.player_id) : res.data.my_team?.vice_captain ? Number(res.data.my_team.vice_captain) : null);
      setMyPenalty(res.data.my_team?.penalty || null);
    } catch {
      toast('Failed to load Super Team.', 'error');
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (tab === 'compare' && !selectedBreakdownUserId) {
      const firstOther = userBreakdowns.find((row) => row.user_id !== myUserId);
      if (firstOther) setSelectedBreakdownUserId(firstOther.user_id);
    }
  }, [myUserId, selectedBreakdownUserId, tab, userBreakdowns]);

  const allPoolPlayers = useMemo(() => roles.flatMap((role) => playersByRole[role] || []), [playersByRole]);

  const availableTeams = useMemo(() => {
    const teams = Array.from(new Set(allPoolPlayers.map((player) => player.team).filter(Boolean)));
    return teams.sort();
  }, [allPoolPlayers]);

  useEffect(() => {
    if (availableTeams.length === 0) {
      setActiveTeam(null);
      return;
    }
    setActiveTeam((current) => (current === MY_TEAM_TAB || (current && availableTeams.includes(current)) ? current : availableTeams[0]));
  }, [availableTeams]);

  const selectedPlayers = useMemo(() => {
    return allPoolPlayers.filter((player) => selected.has(player.id));
  }, [allPoolPlayers, selected]);

  const sortPlayers = (players: Player[]) => {
    return [...players].sort((a, b) => {
      const avgDiff = Number(b.avg_points || 0) - Number(a.avg_points || 0);
      if (avgDiff !== 0) return avgDiff;
      const totalDiff = Number(b.total_points || 0) - Number(a.total_points || 0);
      if (totalDiff !== 0) return totalDiff;
      return a.name.localeCompare(b.name);
    });
  };

  const visibleTeamPlayers = useMemo(() => {
    return sortPlayers(allPoolPlayers.filter((player) => {
      if (activeTeam && player.team !== activeTeam) return false;
      if (activePlayerView !== 'Squad' && player.role !== activePlayerView) return false;
      return true;
    }));
  }, [activePlayerView, activeTeam, allPoolPlayers]);
  const visibleSelectionPlayers = activeTeam === MY_TEAM_TAB ? sortPlayers(selectedPlayers) : visibleTeamPlayers;

  const normalizedPlayerSearch = playerSearch.trim().toLowerCase();
  const playerSearchResults = useMemo(() => {
    if (!normalizedPlayerSearch) return [];
    return sortPlayers(allPoolPlayers.filter((player) => {
      const haystack = `${player.name} ${player.team} ${player.role}`.toLowerCase();
      return haystack.includes(normalizedPlayerSearch);
    }));
  }, [allPoolPlayers, normalizedPlayerSearch]);

  const teamCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    selectedPlayers.forEach((player) => {
      counts[player.team] = (counts[player.team] || 0) + 1;
    });
    return counts;
  }, [selectedPlayers]);

  const bowlerCount = selectedPlayers.filter((player) => player.role === 'Bowler').length;
  const roleCounts = useMemo(() => {
    const counts = roles.reduce<Record<Role, number>>((acc, role) => {
      acc[role] = 0;
      return acc;
    }, {} as Record<Role, number>);
    selectedPlayers.forEach((player) => {
      if (roles.includes(player.role as Role)) {
        const role = player.role as Role;
        counts[role] = (counts[role] || 0) + 1;
      }
    });
    return counts;
  }, [selectedPlayers]);
  const missingRoles = requiredRoles.filter((role) => (roleCounts[role] || 0) < 1);
  const validationMessage = (() => {
    if (selected.size !== SUPER_TEAM_SIZE) return `Select ${SUPER_TEAM_SIZE - selected.size} more players.`;
    if (missingRoles.length > 0) return 'Select at least 1 Wicketkeeper, 1 Batter, and 1 AllRounder.';
    if (bowlerCount < MIN_BOWLERS) return `Select at least ${MIN_BOWLERS} Bowlers.`;
    if (!captain || !selected.has(captain)) return 'Select a Captain.';
    if (!viceCaptain || !selected.has(viceCaptain)) return 'Select a Vice-Captain.';
    if (captain === viceCaptain) return 'Captain and Vice-Captain must be different.';
    return '';
  })();

  const playerSelectionBlockReason = (player: Player) => {
    if (selected.has(player.id)) return '';
    if (!context?.can_edit) return 'Selection is locked.';
    if (selected.size >= SUPER_TEAM_SIZE) return `Maximum ${SUPER_TEAM_SIZE} players selected.`;
    return '';
  };

  useEffect(() => {
    if (!context?.substitution_open || validationMessage || !captain || !viceCaptain) {
      setProjectedPenalty(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const res = await client.post('/api/super-team/penalty-preview', {
          players: [...selected],
          captain,
          vice_captain: viceCaptain,
        });
        if (!cancelled) setProjectedPenalty(res.data || null);
      } catch {
        if (!cancelled) setProjectedPenalty(null);
      }
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [captain, context?.substitution_open, selected, validationMessage, viceCaptain]);

  const togglePlayer = (playerId: number) => {
    if (!context?.can_edit) return;
    setOpenHistoryPlayerId(null);
    const player = allPoolPlayers.find((item) => item.id === playerId);
    if (player) {
      const blockReason = playerSelectionBlockReason(player);
      if (blockReason) {
        toast(blockReason, 'error');
        return;
      }
    }
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(playerId)) {
        next.delete(playerId);
        if (captain === playerId) setCaptain(null);
        if (viceCaptain === playerId) setViceCaptain(null);
      }
      else if (next.size < SUPER_TEAM_SIZE) next.add(playerId);
      else toast(`You can select only ${SUPER_TEAM_SIZE} players.`, 'error');
      return next;
    });
  };

  const save = async () => {
    if (validationMessage) {
      toast(validationMessage, 'error');
      return;
    }
    setSaving(true);
    try {
      await client.post('/api/super-team', { players: [...selected], captain, vice_captain: viceCaptain });
      toast('Super Team saved.');
      await load();
    } catch (err: unknown) {
      toast(apiErrorDetail(err, 'Failed to save Super Team.'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const closePlayerSearch = () => {
    setShowPlayerSearch(false);
    setPlayerSearch('');
  };

  if (loading) {
    return <div className="flex justify-center py-16"><div className="h-8 w-8 animate-spin rounded-full border-b-2 border-white" /></div>;
  }

  if (!context?.visible) {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-8 text-center">
        <h2 className="text-xl font-bold text-white">Super Team</h2>
        <p className="mt-2 text-sm text-white/45">{context?.message || 'Super Team is not visible yet.'}</p>
        <Link to="/dashboard" className="mt-5 inline-flex rounded-xl bg-white px-4 py-2 text-sm font-semibold text-black">Back to Dashboard</Link>
      </div>
    );
  }

  const showSelection = context.enabled && Boolean(context.can_edit);
  const currentStatus = statusLabel(context);
  const leader = standings.find((row) => row.rank === 1);
  const selectedUserBreakdown = userBreakdowns.find((row) => row.user_id === selectedBreakdownUserId)
    || (tab === 'compare' ? userBreakdowns.find((row) => row.user_id !== myUserId) : userBreakdowns[0]);
  const myUserBreakdown = myUserId ? userBreakdowns.find((row) => row.user_id === myUserId) || null : null;
  const aggregateBreakdownPlayers = (entry: SuperUserBreakdown | null | undefined): AggregatedBreakdownPlayer[] => {
    const players = new Map<number, AggregatedBreakdownPlayer>();
    (entry?.matches || []).forEach((match) => {
      match.players.forEach((player) => {
        const existing = players.get(player.player_id);
        if (existing) {
          existing.points += Number(player.points || 0);
          existing.match_points[String(match.match_id)] = Number(player.points || 0);
          existing.substituted = existing.substituted || Boolean(player.removed);
          if (player.tag) existing.tag = player.tag;
          if (player.multiplier) existing.multiplier = player.multiplier;
        } else {
          players.set(player.player_id, {
            ...player,
            points: Number(player.points || 0),
            match_points: { [String(match.match_id)]: Number(player.points || 0) },
            substituted: Boolean(player.removed),
          });
        }
      });
    });
    return [...players.values()].sort((a, b) => b.points - a.points || a.name.localeCompare(b.name));
  };
  const selectedAggregatePlayers = aggregateBreakdownPlayers(selectedUserBreakdown);
  const myAggregatePlayers = aggregateBreakdownPlayers(myUserBreakdown);
  const comparison = (() => {
    if (!myAggregatePlayers.length || !selectedAggregatePlayers.length || selectedUserBreakdown?.user_id === myUserId) return null;
    const mine = new Map(myAggregatePlayers.map((player) => [player.player_id, player]));
    const theirs = new Map(selectedAggregatePlayers.map((player) => [player.player_id, player]));
    const common = [...mine.values()].filter((player) => theirs.has(player.player_id));
    const onlyMine = [...mine.values()].filter((player) => !theirs.has(player.player_id));
    const onlyTheirs = [...theirs.values()].filter((player) => !mine.has(player.player_id));
    const roleDiff = common.filter((player) => (player.tag || '') !== (theirs.get(player.player_id)?.tag || ''));
    const pointDiff = common.filter((player) => {
      const theirsPlayer = theirs.get(player.player_id);
      return (player.tag || '') === (theirsPlayer?.tag || '') && Number(player.points || 0) !== Number(theirsPlayer?.points || 0);
    });
    const commonSame = common.filter((player) => {
      const theirsPlayer = theirs.get(player.player_id);
      return (player.tag || '') === (theirsPlayer?.tag || '') && Number(player.points || 0) === Number(theirsPlayer?.points || 0);
    });
    const differentPlayersDiff = onlyMine.reduce((sum, player) => sum + Number(player.points || 0), 0)
      - onlyTheirs.reduce((sum, player) => sum + Number(player.points || 0), 0);
    const roleDiffTotal = roleDiff.reduce((sum, player) => sum + Number(player.points || 0) - Number(theirs.get(player.player_id)?.points || 0), 0);
    const pointDiffTotal = pointDiff.reduce((sum, player) => sum + Number(player.points || 0) - Number(theirs.get(player.player_id)?.points || 0), 0);
    return { common, commonSame, onlyMine, onlyTheirs, roleDiff, pointDiff, differentPlayersDiff, roleDiffTotal, pointDiffTotal, theirs };
  })();

  const playerStatsRows = playerPointRows
    .map((player) => ({
      ...player,
      match_points_value: Number(player.match_points?.[String(activePlayerStatsMatchId)] || 0),
    }))
    .sort((a, b) => b.match_points_value - a.match_points_value || b.points - a.points || a.name.localeCompare(b.name));
  const compareContestants = userBreakdowns.filter((row) => row.user_id !== myUserId);
  const renderTeamBadge = (team: string, compact = false) => {
    const theme = getTeamTheme(team);
    return (
      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 font-semibold ${compact ? 'text-[9px]' : 'text-[10px]'} ${theme.badgeClass}`}>
        {theme.label}
      </span>
    );
  };
  const shortRole = (role: string) => role === 'Wicketkeeper' ? 'WK' : role === 'Batter' ? 'BAT' : role === 'AllRounder' ? 'AR' : role === 'Bowler' ? 'BOWL' : role;
  const formatSigned = (value: number) => `${value > 0 ? '+' : ''}${formatPoints(value)}`;
  const renderAggregatedPlayers = (players: AggregatedBreakdownPlayer[], keyPrefix: string) => (
    <div className="grid grid-cols-2 gap-2">
      {players.map((player) => (
        <div key={`${keyPrefix}-${player.player_id}`} className={`rounded-xl border border-white/10 bg-gradient-to-r ${getTeamTheme(player.team).tintClass} px-2.5 py-2 ${player.substituted ? 'ring-1 ring-amber-400/25' : ''}`}>
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <p className="truncate text-[13px] font-medium text-white">{player.name}</p>
                {player.tag && (
                  <span className={`inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1.5 text-[9px] font-bold ${player.tag === 'C' ? 'bg-amber-500 text-black' : 'bg-sky-500 text-black'}`}>
                    {player.tag}
                  </span>
                )}
                {player.substituted && (
                  <span className="rounded-full border border-amber-400/20 bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-semibold text-amber-200">
                    Sub
                  </span>
                )}
              </div>
              <div className="mt-1 flex items-center gap-1.5 text-[11px] text-white/40">
                {renderTeamBadge(player.team, true)}
                <span>{shortRole(player.role)}</span>
              </div>
              <p className="mt-1 text-[10px] text-white/30">
                M71 {formatPoints(player.match_points['71'] || 0)} | M72 {formatPoints(player.match_points['72'] || 0)} | M73 {formatPoints(player.match_points['73'] || 0)} | M74 {formatPoints(player.match_points['74'] || 0)}
              </p>
            </div>
            <div className="shrink-0 text-right">
              <p className="text-sm font-bold text-blue-400">{formatPoints(player.points)}</p>
              <p className="text-[10px] text-white/30">Pts</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
  const renderComparePlayerEntry = (player: AggregatedBreakdownPlayer | null | undefined, side: 'left' | 'right') => {
    if (!player) {
      return <div className="flex-1 rounded-xl border border-white/5 bg-black/20 px-3 py-2 text-xs text-white/25">Not selected</div>;
    }
    return (
      <div className={`flex-1 rounded-xl border px-3 py-2 ${side === 'left' ? 'border-blue-500/20 bg-blue-500/10' : 'border-red-500/20 bg-red-500/10'}`}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <p className="truncate text-sm font-semibold text-white">{player.name}</p>
              {player.tag && (
                <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold ${player.tag === 'C' ? 'bg-amber-500 text-black' : 'bg-sky-500 text-black'}`}>
                  {player.tag}
                </span>
              )}
              {player.substituted && <span className="rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-semibold text-amber-200">Sub</span>}
            </div>
            <div className="mt-1 flex items-center gap-1.5 text-[11px] text-white/45">
              {renderTeamBadge(player.team, true)}
              <span>{shortRole(player.role)}</span>
            </div>
            <p className="mt-1 text-[10px] text-white/30">
              M71 {formatPoints(player.match_points['71'] || 0)} | M72 {formatPoints(player.match_points['72'] || 0)} | M73 {formatPoints(player.match_points['73'] || 0)} | M74 {formatPoints(player.match_points['74'] || 0)}
            </p>
          </div>
          <p className="shrink-0 text-sm font-bold text-blue-300">{formatPoints(player.points)}</p>
        </div>
      </div>
    );
  };
  const renderCompareSection = (
    title: string,
    rows: Array<{ left?: AggregatedBreakdownPlayer | null; right?: AggregatedBreakdownPlayer | null; key: string }>,
    total?: number,
  ) => {
    if (rows.length === 0) return null;
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          {total != null && (
            <span className={`rounded-full px-2 py-1 text-xs font-bold ${total > 0 ? 'bg-blue-500/20 text-blue-400' : total < 0 ? 'bg-red-500/20 text-red-400' : 'bg-white/10 text-white'}`}>
              {formatSigned(total)} pts
            </span>
          )}
        </div>
        <div className="space-y-2">
          {rows.map((row) => (
            <div key={row.key} className="flex gap-2">
              {renderComparePlayerEntry(row.left, 'left')}
              {renderComparePlayerEntry(row.right, 'right')}
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-black">
      <header className="mobile-safe-blur sticky top-[56px] z-30 border-b border-white/10 bg-black/80 md:backdrop-blur-lg">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-4">
          <div className="flex min-w-0 items-center gap-3">
            <Link to="/dashboard" className="rounded-xl p-2 transition-all hover:bg-white/10" title="Back" aria-label="Back to dashboard">
              <svg className="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </Link>
            <div className="min-w-0">
              <h1 className="text-lg font-bold text-white">Super Team</h1>
              <p className="truncate text-xs text-white/40">{context.enabled ? context.teams.join(' | ') : context.message}</p>
            </div>
          </div>
          <div className="shrink-0 grid w-[12.75rem] max-w-[52vw] grid-cols-3 gap-1 rounded-xl bg-white/5 p-1 sm:w-[15rem]">
            {SUPER_TABS.map((entry) => (
              <button
                key={entry.key}
                type="button"
                onClick={() => setTab(entry.key)}
                className={`w-full min-w-0 whitespace-nowrap rounded-lg px-1.5 py-1 text-[10px] font-medium transition sm:px-2 sm:text-[11px] ${tab === entry.key ? 'bg-white text-black' : 'text-white/50 hover:text-white'}`}
              >
                {entry.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => setShowRules(true)}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-white/70 transition hover:bg-white/10 hover:text-white"
          >
            What's this?
          </button>
          <button
            onClick={() => {
              setContestantsTab('playing');
              setShowContestants(true);
            }}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-white/70 transition hover:bg-white/10 hover:text-white"
          >
            Who's Playing
          </button>
        </div>

      <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
        <div className="mb-2 flex items-center justify-between gap-3">
          <div>
            <span className="text-sm font-semibold text-white">Playoff Super Team</span>
            <p className="mt-1 text-xs text-white/35">
              {context.enabled ? context.teams.join(' | ') : context.message}
            </p>
          </div>
          <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${currentStatus.color}`}>
            {currentStatus.text}
          </span>
        </div>

        {leader && context.locked && (
          <div className="mb-3 rounded-xl border border-cyan-400/20 bg-cyan-500/10 p-3">
            <p className="text-xs text-cyan-300/70">Current Leader</p>
            <div className="mt-1 flex items-center justify-between gap-3">
              <p className="truncate text-sm font-bold text-cyan-200">{leader.name}</p>
              <p className="text-sm font-bold text-cyan-200">{leader.points} pts</p>
            </div>
          </div>
        )}

        {context.substitution_open && (
          <div className="mb-3 rounded-xl border border-cyan-400/20 bg-cyan-500/10 p-3">
            <p className="text-xs font-semibold text-cyan-200">Substitution window open</p>
            <p className="mt-1 text-xs text-cyan-100/60">
              {context.substitution_phase === 2
                ? 'Changes are compared with your edited team. Final team locks at Match 74 toss.'
                : 'Changes are compared with your original team. Edited team locks at Match 73 toss.'}
            </p>
          </div>
        )}

        {(projectedPenalty || myPenalty) && (projectedPenalty || myPenalty)!.total > 0 && (
          <div className="mb-3 rounded-xl border border-amber-400/20 bg-amber-500/10 p-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs font-semibold text-amber-200">{projectedPenalty ? 'Projected penalty' : 'Current penalty'}</p>
              <p className="text-sm font-bold text-amber-200">-{(projectedPenalty || myPenalty)!.total}</p>
            </div>
            <p className="mt-1 text-[11px] text-amber-100/60">
              New players: -{(projectedPenalty || myPenalty)!.new_player_penalty || 0}
              {(projectedPenalty || myPenalty)!.captain_penalty ? ` | Captain: -${(projectedPenalty || myPenalty)!.captain_penalty}` : ''}
              {(projectedPenalty || myPenalty)!.vice_captain_penalty ? ` | Vice-Captain: -${(projectedPenalty || myPenalty)!.vice_captain_penalty}` : ''}
            </p>
          </div>
        )}

        <div className="mt-2 flex items-center gap-1">
          {[71, 72, 73, 74].map((matchId) => {
            const match = context.matches?.[String(matchId)];
            return (
              <div key={matchId} className="flex-1 text-center">
                <div className="mb-1 text-[9px] text-white/30">M{matchId}</div>
                <div className={`h-1.5 rounded-full ${matchProgressTone(match?.Status)}`} />
                <div className="mt-1 truncate text-[8px] text-white/20">
                  {match ? `${match.Team1} vs ${match.Team2}` : `Match ${matchId}`}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {!context.enabled && (
        <div className="rounded-2xl border border-amber-400/20 bg-amber-500/10 p-5 text-sm text-amber-200">
          {context.message || 'The playoff battle starts once Match 71 and Match 72 teams are confirmed.'}
        </div>
      )}

      {tab === 'live' && context.locked && (
        <div className="rounded-2xl border border-white/10 bg-white/5">
          <div className="border-b border-white/10 px-4 py-3 text-sm font-semibold text-white">Super Team Standings</div>
          <div className="divide-y divide-white/5">
            {standings.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-white/40">No submitted Super Teams.</div>
            ) : standings.map((row) => (
              <div key={row.user_id}>
                <button
                  type="button"
                  onClick={() => setSelectedBreakdownUserId(selectedBreakdownUserId === row.user_id ? null : row.user_id)}
                  className={`flex w-full items-center gap-3 px-4 py-3 text-left transition ${
                    selectedBreakdownUserId === row.user_id ? 'bg-white/8' : row.user_id === myUserId ? 'bg-amber-500/10 hover:bg-amber-500/15' : 'hover:bg-white/[0.03]'
                  }`}
                >
                  <div className="w-10 text-center text-sm font-bold text-white/60">#{row.rank}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-semibold text-white">{row.name}</p>
                      {row.user_id === myUserId && (
                        <span className="rounded-full bg-amber-400/20 px-2 py-0.5 text-[10px] font-semibold text-amber-300">You</span>
                      )}
                    </div>
                    <p className="text-[11px] text-white/35">
                      M71 {formatPoints(row.match_points?.['71'] || 0)} | M72 {formatPoints(row.match_points?.['72'] || 0)} | M73 {formatPoints(row.match_points?.['73'] || 0)} | M74 {formatPoints(row.match_points?.['74'] || 0)}
                      {row.penalty?.total ? ` | Penalty -${row.penalty.total}` : ''}
                    </p>
                  </div>
                  <div className="shrink-0 text-sm font-bold text-blue-300">{formatPoints(row.points)} pts</div>
                  <span className={`text-[10px] text-white/40 transition-transform ${selectedBreakdownUserId === row.user_id ? 'rotate-90' : ''}`}>&#9654;</span>
                </button>
                {selectedBreakdownUserId === row.user_id && selectedUserBreakdown && (
                  <div className="border-t border-white/5 bg-black/20 px-4 py-4">
                    <div className="mb-3 flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-xs uppercase tracking-[0.2em] text-white/35">Team View</p>
                        <h3 className="truncate text-sm font-semibold text-white">{selectedUserBreakdown.name}</h3>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-bold text-blue-400">{formatPoints(selectedUserBreakdown.points)} pts</p>
                        {selectedUserBreakdown.penalty?.total ? <p className="text-[10px] text-amber-300">-{selectedUserBreakdown.penalty.total} penalty</p> : null}
                      </div>
                    </div>
                    {renderAggregatedPlayers(selectedAggregatePlayers, 'live-open')}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'live' && context.locked && (
        <div className="rounded-2xl border border-white/10 bg-white/5">
          <div className="border-b border-white/10 px-4 py-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-semibold text-white">Player Statistics</p>
                <p className="text-xs text-white/35">Select a playoff match to view player points for that match.</p>
              </div>
              <div className="grid grid-cols-4 gap-1 rounded-xl bg-black/25 p-1">
                {[71, 72, 73, 74].map((matchId) => (
                  <button
                    key={matchId}
                    type="button"
                    onClick={() => setActivePlayerStatsMatchId(matchId)}
                    className={`rounded-lg px-2 py-1.5 text-xs font-semibold transition ${
                      activePlayerStatsMatchId === matchId ? 'bg-white text-black' : 'text-white/55 hover:bg-white/10'
                    }`}
                  >
                    M{matchId}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="divide-y divide-white/5">
            {playerStatsRows.length === 0 ? (
              <div className="px-4 py-8 text-center text-white/40">Player points will appear once playoff scoring starts.</div>
            ) : playerStatsRows.map((player) => (
              <div key={`${activePlayerStatsMatchId}-${player.player_id}`}>
                <div
                  onClick={() => setExpandedStatsPlayerId(expandedStatsPlayerId === player.player_id ? null : player.player_id)}
                  className={`flex cursor-pointer items-center justify-between gap-3 bg-gradient-to-r ${getTeamTheme(player.team).tintClass} px-4 py-3 transition-colors hover:bg-white/5`}
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <span className={`text-[10px] text-white/40 transition-transform ${expandedStatsPlayerId === player.player_id ? 'rotate-90' : ''}`}>&#9654;</span>
                    {renderTeamBadge(player.team, true)}
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-white">{player.name}</p>
                      <p className="text-xs text-white/35">{shortRole(player.role)}</p>
                    </div>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className={`text-sm font-bold ${player.match_points_value ? 'text-blue-300' : 'text-white/30'}`}>
                      {formatPoints(player.match_points_value)}
                    </p>
                    <p className="text-[10px] text-white/30">M{activePlayerStatsMatchId} pts</p>
                  </div>
                </div>
                {expandedStatsPlayerId === player.player_id && (
                  <div className="border-t border-white/10 bg-black px-4 py-3">
                    <p className="mb-2 text-[10px] uppercase tracking-wider text-white/40">Player Analysis</p>
                    {(player.match_breakdowns?.[String(activePlayerStatsMatchId)] || []).length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {(player.match_breakdowns?.[String(activePlayerStatsMatchId)] || []).map((item, index) => (
                          <span key={`${player.player_id}-${activePlayerStatsMatchId}-${index}`} className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium ${
                            item.points > 0 ? 'border-blue-500/20 bg-blue-500/10 text-blue-400' : 'border-red-500/20 bg-red-500/10 text-red-400'
                          }`}>
                            {item.label} <span className="font-bold">{item.points > 0 ? '+' : ''}{formatPoints(item.points)}</span>
                          </span>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-white/35">No detailed point breakdown available for this match.</p>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'myteam' && !showSelection && myUserBreakdown && (
        <div className="space-y-4">
          <div className="rounded-2xl overflow-hidden shadow-2xl max-w-md mx-auto"
            style={{ background: 'linear-gradient(180deg, #1a5e1a 0%, #2d8a2d 30%, #3da33d 50%, #2d8a2d 70%, #1a5e1a 100%)' }}>
            <div className="text-center pt-4 pb-2">
              <p className="text-blue-400 text-lg font-bold">{formatPoints(myUserBreakdown.points)} <span className="text-sm text-blue-200/70">pts</span></p>
              <p className="text-white/40 text-[10px] uppercase tracking-widest">Team Analysis</p>
            </div>
            <div className="relative px-4 pb-5">
              <div className="absolute inset-x-8 inset-y-4 rounded-[50%] border-2 border-white/15" />
              {roles.map((role) => {
                const rolePlayers = myAggregatePlayers.filter((player) => player.role === role);
                if (rolePlayers.length === 0) return null;
                const roleLabel = role === 'AllRounder' ? 'All Rounders' : role === 'Wicketkeeper' ? 'Wicketkeeper' : `${role}s`;
                return (
                  <div key={role} className="relative z-10 mb-3">
                    <p className="mb-1.5 text-center text-[9px] uppercase tracking-widest text-white/30">{roleLabel}</p>
                    <div className="flex flex-wrap justify-center gap-2">
                      {rolePlayers.map((player) => (
                        <div key={`ground-${player.player_id}`} className="flex flex-col items-center">
                          <div className={`flex h-10 w-10 items-center justify-center rounded-full text-[10px] font-bold shadow-lg ${
                            player.tag === 'C' ? 'bg-amber-400 text-black ring-2 ring-amber-300' :
                            player.tag === 'VC' ? 'bg-sky-400 text-black ring-2 ring-sky-300' :
                            player.substituted ? 'bg-amber-200 text-amber-950' : 'bg-white text-blue-900'
                          }`}>
                            {player.tag || formatPoints(player.points)}
                          </div>
                          <p className="mt-0.5 max-w-[55px] truncate text-center text-[9px] font-medium text-white">{player.name.split(' ').pop()}</p>
                          <p className="text-[9px] font-bold text-blue-300">{formatPoints(player.points)}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="flex justify-center gap-4 pb-3 text-[9px] text-white/40">
              <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-amber-400" /> C</span>
              <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-sky-400" /> VC</span>
              <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-amber-200" /> Sub</span>
            </div>
          </div>

          <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/5">
            <div className="border-b border-white/10 px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-white">Player Contributions</h3>
                  <p className="text-[10px] text-white/35">All selected players with substitution indicators</p>
                </div>
                <p className="text-sm font-bold text-blue-400">{formatPoints(myUserBreakdown.points)} pts</p>
              </div>
            </div>
            <div className="p-3">
              {renderAggregatedPlayers(myAggregatePlayers, 'myteam')}
            </div>
          </div>
        </div>
      )}

      {tab === 'compare' && context.locked && (
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <h2 className="mb-3 text-sm font-semibold text-white">Compare Teams</h2>
          {compareContestants.length === 0 ? (
            <p className="text-sm text-white/40">No other Super Teams are available to compare yet.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {compareContestants.map((row) => (
                <button
                  key={row.user_id}
                  type="button"
                  onClick={() => setSelectedBreakdownUserId(row.user_id)}
                  className={`rounded-xl px-4 py-2 text-sm font-medium transition ${
                    selectedBreakdownUserId === row.user_id ? 'bg-white text-black' : 'bg-white/10 text-white/50 hover:bg-white/20'
                  }`}
                >
                  #{row.rank} {row.name}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'compare' && context.locked && selectedUserBreakdown && selectedUserBreakdown.user_id !== myUserId && (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-2xl border border-white/20 bg-white/10 p-4 text-center">
              <p className="mb-1 text-xs font-medium text-white/50">You</p>
              <p className="text-2xl font-bold text-white">{formatPoints(myUserBreakdown?.points || 0)}</p>
            </div>
            <div className={`${Number(myUserBreakdown?.points || 0) - Number(selectedUserBreakdown.points || 0) >= 0 ? 'border-blue-500/20 bg-blue-500/10' : 'border-red-500/20 bg-red-500/10'} rounded-2xl border p-4 text-center`}>
              <p className="mb-1 text-xs font-medium text-white/50">Diff</p>
              {(() => {
                const diff = Number(myUserBreakdown?.points || 0) - Number(selectedUserBreakdown.points || 0);
                return <p className={`text-2xl font-bold ${diff >= 0 ? 'text-blue-400' : 'text-red-400'}`}>{diff > 0 ? '+' : ''}{formatPoints(diff)}</p>;
              })()}
            </div>
            <div className="rounded-2xl border border-red-500/20 bg-red-500/10 p-4 text-center">
              <p className="mb-1 truncate text-xs font-medium text-red-300">{selectedUserBreakdown.name}</p>
              <p className="text-2xl font-bold text-white">{formatPoints(selectedUserBreakdown.points)}</p>
            </div>
          </div>

          {comparison && (
            <>
              {renderCompareSection(
                'Different Players',
                Array.from({ length: Math.max(comparison.onlyMine.length, comparison.onlyTheirs.length) }, (_, index) => ({
                  key: `different-${index}`,
                  left: comparison.onlyMine[index] || null,
                  right: comparison.onlyTheirs[index] || null,
                })),
                comparison.differentPlayersDiff,
              )}

              {renderCompareSection(
                'Same Players, Different C/VC',
                comparison.roleDiff.map((left) => ({
                  key: `role-${left.player_id}`,
                  left,
                  right: comparison.theirs.get(left.player_id) || null,
                })),
                comparison.roleDiffTotal,
              )}

              {renderCompareSection(
                'Same Players, Different Points',
                comparison.pointDiff.map((left) => ({
                  key: `points-${left.player_id}`,
                  left,
                  right: comparison.theirs.get(left.player_id) || null,
                })),
                comparison.pointDiffTotal,
              )}

              {renderCompareSection(
                'Common Players',
                comparison.commonSame.map((left) => ({
                  key: `common-${left.player_id}`,
                  left,
                  right: comparison.theirs.get(left.player_id) || null,
                })),
              )}
            </>
          )}
        </div>
      )}

      {tab === 'myteam' && showSelection && (
        <>
          <div className="-mx-4 overflow-x-auto px-4">
            <div className="flex min-w-max gap-2 rounded-xl border border-white/10 bg-white/5 p-2">
              <div className="min-w-20 rounded-lg bg-black/30 px-3 py-2 text-center">
                <p className="text-[11px] text-white/35">Selected</p>
                <p className="text-sm font-bold text-white">{selected.size}/{SUPER_TEAM_SIZE}</p>
              </div>
              <div className="min-w-20 rounded-lg bg-black/30 px-3 py-2 text-center">
                <p className="text-[11px] text-white/35">Bowlers</p>
                <p className={`text-sm font-bold ${bowlerCount >= MIN_BOWLERS ? 'text-blue-300' : 'text-amber-300'}`}>{bowlerCount}/{MIN_BOWLERS}</p>
              </div>
              <div className="min-w-20 rounded-lg bg-black/30 px-3 py-2 text-center">
                <p className="text-[11px] text-white/35">C / VC</p>
                <p className={`text-sm font-bold ${captain && viceCaptain && captain !== viceCaptain ? 'text-blue-300' : 'text-amber-300'}`}>
                  {(captain ? 1 : 0) + (viceCaptain ? 1 : 0)}/2
                </p>
              </div>
            </div>
          </div>

          <div className="-mx-4 overflow-x-auto px-4">
            <div className="flex min-w-max gap-1 rounded-xl border border-white/10 bg-white/5 p-1">
              <button
                type="button"
                onClick={() => {
                  setActiveTeam(MY_TEAM_TAB);
                  setShowPlayerSearch(false);
                  setPlayerSearch('');
                  setOpenHistoryPlayerId(null);
                }}
                className={`rounded-lg px-4 py-2 text-xs font-semibold transition ${activeTeam === MY_TEAM_TAB ? 'bg-white text-black' : 'text-white/55 hover:bg-white/10'}`}
              >
                My Team
                <span className={`ml-2 rounded-full px-1.5 py-0.5 text-[10px] ${activeTeam === MY_TEAM_TAB ? 'bg-black/10 text-black/70' : 'bg-white/10 text-white/60'}`}>
                  {selected.size}
                </span>
              </button>
              {availableTeams.map((team) => (
                <button
                  key={team}
                  type="button"
                  onClick={() => {
                    setActiveTeam(team);
                    setOpenHistoryPlayerId(null);
                  }}
                  className={`rounded-lg px-4 py-2 text-xs font-semibold transition ${activeTeam === team ? 'bg-white text-black' : 'text-white/55 hover:bg-white/10'}`}
                >
                  {team}
                  <span className={`ml-2 rounded-full px-1.5 py-0.5 text-[10px] ${activeTeam === team ? 'bg-black/10 text-black/70' : 'bg-white/10 text-white/60'}`}>
                    {teamCounts[team] || 0}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {activeTeam !== MY_TEAM_TAB && (
          <div className="-mx-4 overflow-x-auto px-4">
            <div className="flex min-w-max gap-1 rounded-xl border border-white/10 bg-white/5 p-1">
              {(['Squad', ...roles] as PlayerView[]).map((view) => (
                <button
                  key={view}
                  type="button"
                  onClick={() => setActivePlayerView(view)}
                  className={`min-w-14 rounded-lg px-3 py-2 text-xs font-semibold transition ${activePlayerView === view ? 'bg-white text-black' : 'text-white/55 hover:bg-white/10'}`}
                >
                  {view === 'Squad' ? 'Squad' : view === 'Wicketkeeper' ? 'WK' : view === 'Batter' ? 'BAT' : view === 'AllRounder' ? 'AR' : 'BALL'}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setShowPlayerSearch(true)}
                className="inline-flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-white/60 transition hover:bg-white/10 hover:text-white"
                aria-label="Search players"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="m21 21-4.35-4.35m1.85-5.15a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z" />
                </svg>
              </button>
            </div>
          </div>
          )}

          {showPlayerSearch && (
            <div className="flex items-center gap-2 rounded-2xl border border-white/10 bg-white/[0.04] px-3 py-2">
              <svg className="h-4 w-4 flex-shrink-0 text-white/40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="m21 21-4.35-4.35m1.85-5.15a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z" />
              </svg>
              <input
                type="text"
                value={playerSearch}
                onChange={(e) => setPlayerSearch(e.target.value)}
                placeholder="Search players from playoff squads"
                autoFocus
                className="min-w-0 flex-1 bg-transparent text-sm text-white placeholder:text-white/30 focus:outline-none"
              />
              <button
                type="button"
                onClick={closePlayerSearch}
                className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/5 text-white/60 transition hover:bg-white/10 hover:text-white"
                aria-label="Close player search"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18 18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            {(showPlayerSearch && normalizedPlayerSearch && activeTeam !== MY_TEAM_TAB ? playerSearchResults : visibleSelectionPlayers).map((player) => {
              const isSelected = selected.has(player.id);
              const isCaptain = captain === player.id;
              const isViceCaptain = viceCaptain === player.id;
              const blockReason = playerSelectionBlockReason(player);
              const isSelectionBlocked = Boolean(blockReason);
              return (
                <div
                  key={player.id}
                  onClick={() => togglePlayer(player.id)}
                  title={blockReason || undefined}
                  className={`relative rounded-2xl border p-4 text-left transition ${openHistoryPlayerId === player.id ? 'z-40' : 'z-10'} ${
                    isSelectionBlocked ? 'cursor-not-allowed border-white/5 bg-white/[0.025]' : 'cursor-pointer'
                  } ${isSelected ? 'border-blue-400/60 bg-blue-500/15' : isSelectionBlocked ? '' : 'border-white/10 bg-white/5 hover:bg-white/10'}`}
                >
                  <div className="flex items-start gap-3">
                    <PlayerHistoryToggle
                      player={player}
                      isOpen={openHistoryPlayerId === player.id}
                      isSelected={isSelected}
                      onToggle={() => setOpenHistoryPlayerId((current) => (current === player.id ? null : player.id))}
                    />
                    <div className={`min-w-0 flex-1 ${isSelectionBlocked ? 'opacity-45' : ''}`}>
                      <p className="truncate text-sm font-semibold text-white">{player.name}</p>
                      <p className="text-xs text-white/40">{player.team} | {player.role}</p>
                    </div>
                    <div className={`flex flex-shrink-0 items-center gap-1 ${isSelectionBlocked ? 'opacity-45' : ''}`}>
                      {isSelected && (
                        <>
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              setCaptain((current) => (current === player.id ? null : player.id));
                              if (viceCaptain === player.id) setViceCaptain(null);
                            }}
                            className={`rounded-lg px-2 py-1 text-xs font-bold ${isCaptain ? 'bg-amber-400 text-black' : 'bg-white/10 text-white/50'}`}
                          >
                            C
                          </button>
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              setViceCaptain((current) => (current === player.id ? null : player.id));
                              if (captain === player.id) setCaptain(null);
                            }}
                            className={`rounded-lg px-2 py-1 text-xs font-bold ${isViceCaptain ? 'bg-cyan-400 text-black' : 'bg-white/10 text-white/50'}`}
                          >
                            VC
                          </button>
                        </>
                      )}
                      <span className={`rounded-lg px-2 py-1 text-xs font-bold ${isSelected ? 'bg-blue-400 text-black' : 'bg-white/10 text-white/40'}`}>
                        {isSelected ? 'Selected' : isSelectionBlocked ? 'Full' : '+'}
                      </span>
                    </div>
                  </div>
                  <p className={`mt-3 text-xs text-white/55 ${isSelectionBlocked ? 'opacity-45' : ''}`}>{statText(player)}</p>
                  {isSelectionBlocked && (
                    <p className="mt-2 text-[11px] font-medium text-white/35">{blockReason}</p>
                  )}
                </div>
              );
            })}
            {showPlayerSearch && normalizedPlayerSearch && playerSearchResults.length === 0 && (
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-8 text-center text-sm text-white/40 sm:col-span-2">
                No players found.
              </div>
            )}
            {activeTeam === MY_TEAM_TAB && visibleSelectionPlayers.length === 0 && (
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-8 text-center text-sm text-white/40 sm:col-span-2">
                No players selected yet.
              </div>
            )}
          </div>

          <div className="sticky bottom-0 z-50 -mx-4 border-t border-white/10 bg-black px-4 py-3 shadow-2xl shadow-black">
            <div className="mx-auto flex max-w-6xl items-center justify-between gap-3">
              <p className={`text-xs ${validationMessage ? 'text-amber-300' : 'text-blue-300'}`}>{validationMessage || 'Ready to submit.'}</p>
              <button onClick={save} disabled={saving || Boolean(validationMessage)} className="rounded-xl bg-blue-500 px-5 py-2.5 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-40">
                {saving ? 'Saving...' : 'Save Super Team'}
              </button>
            </div>
          </div>
        </>
      )}
      </main>

      {showRules && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-4 py-6 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-3xl border border-white/10 bg-[#07130d]/98 shadow-2xl shadow-black/60">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-cyan-300">Super Team</p>
                <h3 className="text-lg font-bold text-white">What's this?</h3>
              </div>
              <button
                type="button"
                onClick={() => setShowRules(false)}
                className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-semibold text-white/60 transition hover:bg-white/10 hover:text-white"
              >
                Close
              </button>
            </div>
            <div className="space-y-3 px-5 py-4 text-sm text-white/70">
              {superTeamRules.map((rule, index) => (
                <div key={index} className="flex gap-3 rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5">
                  <span className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-cyan-500/20 text-[11px] font-bold text-cyan-300">
                    {index + 1}
                  </span>
                  <span>{rule}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {showContestants && (
        <Modal title="Super Team Players" onClose={() => setShowContestants(false)}>
          <div className="mb-3 inline-flex rounded-lg bg-white/5 p-1">
            <button
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${contestantsTab === 'playing' ? 'bg-white text-black' : 'text-white/70'}`}
              onClick={() => setContestantsTab('playing')}
            >
              Who's Playing ({contestants.length})
            </button>
            <button
              className={`ml-1 rounded-lg px-3 py-1.5 text-sm font-medium transition ${contestantsTab === 'missing' ? 'bg-white text-black' : 'text-white/70'}`}
              onClick={() => setContestantsTab('missing')}
            >
              Who's Missing ({missingUsers.length})
            </button>
          </div>
          <div className="max-h-[60vh] overflow-auto rounded-xl border border-white/10 bg-white/5">
            {contestantsTab === 'playing' ? (
              contestants.length === 0 ? (
                <p className="px-4 py-6 text-center text-sm text-white/40">No teams submitted yet.</p>
              ) : (
                <div className="divide-y divide-white/5">
                  {contestants.map((row) => (
                    <div key={row.user_id} className="flex items-center justify-between gap-4 px-4 py-3">
                      <span className="text-sm font-medium text-white">{row.name}</span>
                      <div className="text-right">
                        <p className="text-[11px] uppercase tracking-wide text-white/30">Last updated</p>
                        <p className="text-xs text-white/65">{row.last_team_updated || '-'}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )
            ) : missingUsers.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-white/40">No missing users.</p>
            ) : (
              <div className="divide-y divide-white/5">
                {missingUsers.map((row) => (
                  <div key={row.id} className="px-4 py-3">
                    <span className="text-sm font-medium text-white">{row.name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Modal>
      )}
    </div>
  );
}

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4">
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#0f0f0f] p-5 shadow-2xl">
        <div className="mb-4 flex items-center justify-between gap-4">
          <h3 className="text-lg font-bold text-white">{title}</h3>
          <button onClick={onClose} className="rounded-lg p-2 text-white/50 hover:bg-white/10 hover:text-white">X</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function PlayerHistoryToggle({
  player,
  isOpen,
  isSelected,
  onToggle,
}: {
  player: Player;
  isOpen: boolean;
  isSelected: boolean;
  onToggle: () => void;
}) {
  const recentHistory = player.recent_history || [];

  return (
    <div className="relative z-[70] flex-shrink-0 self-start">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onToggle();
        }}
        aria-label={`Toggle recent history for ${player.name}`}
        aria-expanded={isOpen}
        className={`flex h-7 w-7 items-center justify-center rounded-full border transition-all ${
          isOpen
            ? 'border-sky-300/80 bg-sky-400/45 text-sky-50 shadow-lg shadow-sky-400/20'
            : isSelected
            ? 'border-sky-300/70 bg-sky-400/30 text-sky-50 hover:border-sky-200/90 hover:bg-sky-400/40'
            : 'border-white/25 bg-white/15 text-white/80 hover:border-white/45 hover:bg-white/20'
        }`}
      >
        <svg className={`h-3.5 w-3.5 transition-transform ${isOpen ? 'rotate-180' : ''}`} viewBox="0 0 20 20" fill="currentColor">
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {isOpen && (
        <div
          className="absolute left-0 top-full z-[80] mt-2 w-48 overflow-hidden rounded-2xl border border-white/20 bg-black shadow-2xl shadow-black/80 ring-1 ring-black/30"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="border-b border-white/10 bg-black px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-300">Recent Form</div>
          </div>
          <div className="max-h-48 overflow-y-auto bg-black px-3 py-2">
            {recentHistory.length > 0 ? (
              recentHistory.map((entry) => (
                <div key={`${player.id}-${entry.match_id}`} className="flex items-center justify-between gap-3 border-b border-white/5 py-2 last:border-b-0">
                  <span className="text-xs text-white/80">
                    Match#{entry.match_id}{entry.opponent ? ` vs ${entry.opponent}` : ''}
                  </span>
                  <span className={`text-xs font-semibold ${entry.did_not_play ? 'text-white/40' : 'text-blue-300'}`}>
                    {entry.did_not_play ? 'DNP' : formatPoints(entry.points)}
                  </span>
                </div>
              ))
            ) : (
              <div className="py-3 text-xs text-white/40">No completed matches yet.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
