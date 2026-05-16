import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import client from '../api/client';
import { useToast } from '../components/Toast';
import type { Player } from '../types';

type Role = 'Wicketkeeper' | 'Batter' | 'AllRounder' | 'Bowler';
type SuperContext = {
  visible: boolean;
  enabled: boolean;
  locked: boolean;
  bonus_visible: boolean;
  teams: string[];
  message: string;
  matches?: Record<string, { Team1: string; Team2: string; Date: string; Time: string; Status?: string | null }>;
};
type Contestant = { user_id: number; name: string; last_team_updated: string | null };
type MissingUser = { id: number; name: string };
type Standing = { user_id: number; name: string; points: number; rank: number; match_points: Record<string, number> };
type SuperBreakdownPlayer = { player_id: number; name: string; team: string; role: Role; points: number };
type SuperBreakdownMatch = { match_id: number; points: number; players: SuperBreakdownPlayer[] };
type SuperUserBreakdown = Standing & { matches: SuperBreakdownMatch[] };
type SuperPlayerPoints = {
  player_id: number;
  name: string;
  team: string;
  role: Role;
  points: number;
  match_points: Record<string, number>;
};
type MyTeamPlayer = { player_id: number | string };

const roles: Role[] = ['Wicketkeeper', 'Batter', 'AllRounder', 'Bowler'];
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
  const [standings, setStandings] = useState<Standing[]>([]);
  const [userBreakdowns, setUserBreakdowns] = useState<SuperUserBreakdown[]>([]);
  const [playerPointRows, setPlayerPointRows] = useState<SuperPlayerPoints[]>([]);
  const [selectedBreakdownUserId, setSelectedBreakdownUserId] = useState<number | null>(null);
  const [activeBreakdownMatchId, setActiveBreakdownMatchId] = useState(71);
  const [contestants, setContestants] = useState<Contestant[]>([]);
  const [missingUsers, setMissingUsers] = useState<MissingUser[]>([]);
  const [contestantsTab, setContestantsTab] = useState<'playing' | 'missing'>('playing');
  const [activeRole, setActiveRole] = useState<Role>('Wicketkeeper');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [showContestants, setShowContestants] = useState(false);
  const [showPlayerSearch, setShowPlayerSearch] = useState(false);
  const [playerSearch, setPlayerSearch] = useState('');
  const [openHistoryPlayerId, setOpenHistoryPlayerId] = useState<number | null>(null);
  const superTeamRules = [
    'Super Team is a one-time playoff squad for Matches 71-74.',
    'Pick 11 players from the four teams playing Match 71 and Match 72.',
    'Your job is to predict who will progress: players can score again if their team reaches Match 73 or Match 74.',
    'You must select at least 3 Bowlers and at least 1 player from each of the four teams.',
    'No captain, vice-captain, backups, substitutes, or Playing XI availability rules apply.',
    'Team selection locks at the scheduled start time of Match 71.',
    'After Match 74 is complete, the highest Super Team score gets +400 leaderboard bonus. Tied winners all get the bonus.',
  ];

  const load = useCallback(async () => {
    try {
      const res = await client.get('/api/super-team');
      setContext(res.data.context);
      setPlayersByRole(res.data.players || {});
      setStandings(res.data.standings || []);
      setUserBreakdowns(res.data.details?.user_breakdowns || []);
      setPlayerPointRows(res.data.details?.player_points || []);
      setContestants(res.data.contestants || []);
      setMissingUsers(res.data.missing_users || []);
      const myTeamPlayers = (res.data.my_team?.players || []) as MyTeamPlayer[];
      const ids = myTeamPlayers.map((player) => Number(player.player_id));
      setSelected(new Set(ids));
    } catch {
      toast('Failed to load Super Team.', 'error');
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedPlayers = useMemo(() => {
    const all = roles.flatMap((role) => playersByRole[role] || []);
    return all.filter((player) => selected.has(player.id));
  }, [playersByRole, selected]);

  const sortPlayers = (players: Player[]) => {
    return [...players].sort((a, b) => {
      const avgDiff = Number(b.avg_points || 0) - Number(a.avg_points || 0);
      if (avgDiff !== 0) return avgDiff;
      const totalDiff = Number(b.total_points || 0) - Number(a.total_points || 0);
      if (totalDiff !== 0) return totalDiff;
      return a.name.localeCompare(b.name);
    });
  };

  const visibleRolePlayers = useMemo(() => {
    return sortPlayers(playersByRole[activeRole] || []);
  }, [activeRole, playersByRole]);

  const normalizedPlayerSearch = playerSearch.trim().toLowerCase();
  const playerSearchResults = useMemo(() => {
    if (!normalizedPlayerSearch) return [];
    return sortPlayers(roles.flatMap((role) => playersByRole[role] || []).filter((player) => {
      const haystack = `${player.name} ${player.team} ${player.role}`.toLowerCase();
      return haystack.includes(normalizedPlayerSearch);
    }));
  }, [normalizedPlayerSearch, playersByRole]);

  const teamCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    selectedPlayers.forEach((player) => {
      counts[player.team] = (counts[player.team] || 0) + 1;
    });
    return counts;
  }, [selectedPlayers]);

  const bowlerCount = selectedPlayers.filter((player) => player.role === 'Bowler').length;
  const missingTeams = (context?.teams || []).filter((team) => !teamCounts[team]);
  const validationMessage = (() => {
    if (selected.size !== 11) return `Select ${11 - selected.size} more players.`;
    if (bowlerCount < 3) return 'Select at least 3 Bowlers.';
    if (missingTeams.length > 0) return 'Select at least 1 player from each team.';
    return '';
  })();

  const togglePlayer = (playerId: number) => {
    if (context?.locked) return;
    setOpenHistoryPlayerId(null);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(playerId)) next.delete(playerId);
      else if (next.size < 11) next.add(playerId);
      else toast('You can select only 11 players.', 'error');
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
      await client.post('/api/super-team', { players: [...selected] });
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

  const showSelection = context.enabled && !context.locked;
  const currentStatus = statusLabel(context);
  const leader = standings.find((row) => row.rank === 1);
  const selectedUserBreakdown = userBreakdowns.find((row) => row.user_id === selectedBreakdownUserId) || userBreakdowns[0];
  const selectedMatchBreakdown = selectedUserBreakdown?.matches.find((match) => match.match_id === activeBreakdownMatchId) || selectedUserBreakdown?.matches[0];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-xl font-bold text-white">Super Team</h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowRules(true)}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-white/70 transition hover:bg-white/10 hover:text-white"
          >
            What's this?
          </button>
          <Link to="/dashboard" className="p-2 hover:bg-white/10 rounded-xl transition-all" title="Back" aria-label="Back to dashboard">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </Link>
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
          Opens once Match 71 and Match 72 teams are confirmed.
        </div>
      )}

      {context.locked && (
        <div className="rounded-2xl border border-white/10 bg-white/5">
          <div className="border-b border-white/10 px-4 py-3 text-sm font-semibold text-white">Super Team Standings</div>
          <div className="divide-y divide-white/5">
            {standings.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-white/40">No submitted Super Teams.</div>
            ) : standings.map((row) => (
              <button
                key={row.user_id}
                type="button"
                onClick={() => setSelectedBreakdownUserId(row.user_id)}
                className={`flex w-full items-center gap-3 px-4 py-3 text-left transition ${
                  selectedUserBreakdown?.user_id === row.user_id ? 'bg-cyan-500/10' : 'hover:bg-white/[0.03]'
                }`}
              >
                <div className="w-10 text-center text-sm font-bold text-white/60">#{row.rank}</div>
                <div className="flex-1 min-w-0">
                  <p className="truncate text-sm font-semibold text-white">{row.name}</p>
                  <p className="text-[11px] text-white/35">M71 {row.match_points?.['71'] || 0} | M72 {row.match_points?.['72'] || 0} | M73 {row.match_points?.['73'] || 0} | M74 {row.match_points?.['74'] || 0}</p>
                </div>
                <div className="text-sm font-bold text-blue-300">{row.points} pts</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {context.locked && selectedUserBreakdown && (
        <div className="rounded-2xl border border-white/10 bg-white/5">
          <div className="border-b border-white/10 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-white">
                  #{selectedUserBreakdown.rank} {selectedUserBreakdown.name}
                </p>
                <p className="text-xs text-white/35">Selected player points by playoff match</p>
              </div>
              <p className="text-sm font-bold text-cyan-200">{formatPoints(selectedUserBreakdown.points)} pts</p>
            </div>
          </div>
          <div className="border-b border-white/10 p-2">
            <div className="grid grid-cols-4 gap-1 rounded-xl bg-black/25 p-1">
              {[71, 72, 73, 74].map((matchId) => {
                const match = selectedUserBreakdown.matches.find((item) => item.match_id === matchId);
                return (
                  <button
                    key={matchId}
                    type="button"
                    onClick={() => setActiveBreakdownMatchId(matchId)}
                    className={`rounded-lg px-2 py-2 text-xs font-semibold transition ${
                      activeBreakdownMatchId === matchId ? 'bg-white text-black' : 'text-white/55 hover:bg-white/10'
                    }`}
                  >
                    M{matchId} <span className="font-bold">{formatPoints(match?.points || 0)}</span>
                  </button>
                );
              })}
            </div>
          </div>
          <div className="divide-y divide-white/5">
            {(selectedMatchBreakdown?.players || []).map((player) => (
              <div key={`${selectedMatchBreakdown?.match_id}-${player.player_id}`} className="flex items-center justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-white">{player.name}</p>
                  <p className="text-xs text-white/35">{player.team} | {player.role}</p>
                </div>
                <p className={`text-sm font-bold ${player.points ? 'text-blue-300' : 'text-white/30'}`}>{formatPoints(player.points)}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {context.locked && (
        <div className="rounded-2xl border border-white/10 bg-white/5">
          <div className="border-b border-white/10 px-4 py-3">
            <p className="text-sm font-semibold text-white">Player Points</p>
            <p className="text-xs text-white/35">Total points scored by selected Super Team players, broken down match-wise.</p>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-white/10 text-xs uppercase tracking-wide text-white/35">
                <tr>
                  <th className="px-4 py-3 font-semibold">Player</th>
                  <th className="px-3 py-3 text-right font-semibold">M71</th>
                  <th className="px-3 py-3 text-right font-semibold">M72</th>
                  <th className="px-3 py-3 text-right font-semibold">M73</th>
                  <th className="px-3 py-3 text-right font-semibold">M74</th>
                  <th className="px-4 py-3 text-right font-semibold">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {playerPointRows.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-white/40">Player points will appear once playoff scoring starts.</td>
                  </tr>
                ) : playerPointRows.map((player) => (
                  <tr key={player.player_id}>
                    <td className="px-4 py-3">
                      <p className="font-semibold text-white">{player.name}</p>
                      <p className="text-xs text-white/35">{player.team} | {player.role}</p>
                    </td>
                    {[71, 72, 73, 74].map((matchId) => (
                      <td key={matchId} className="px-3 py-3 text-right text-white/70">
                        {formatPoints(player.match_points?.[String(matchId)] || 0)}
                      </td>
                    ))}
                    <td className="px-4 py-3 text-right font-bold text-blue-300">{formatPoints(player.points)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showSelection && (
        <>
          <div className="grid gap-2 rounded-2xl border border-white/10 bg-white/5 p-3 sm:grid-cols-4">
            <div className="rounded-xl bg-black/30 p-3 text-center">
              <p className="text-[11px] text-white/35">Selected</p>
              <p className="text-lg font-bold text-white">{selected.size}/11</p>
            </div>
            <div className="rounded-xl bg-black/30 p-3 text-center">
              <p className="text-[11px] text-white/35">Bowlers</p>
              <p className={`text-lg font-bold ${bowlerCount >= 3 ? 'text-blue-300' : 'text-amber-300'}`}>{bowlerCount}/3</p>
            </div>
            {(context.teams || []).map((team) => (
              <div key={team} className="rounded-xl bg-black/30 p-3 text-center">
                <p className="truncate text-[11px] text-white/35">{team}</p>
                <p className={`text-lg font-bold ${teamCounts[team] ? 'text-blue-300' : 'text-amber-300'}`}>{teamCounts[team] || 0}</p>
              </div>
            ))}
          </div>

          <div className="flex gap-1 rounded-xl border border-white/10 bg-white/5 p-1">
            {roles.map((role) => (
              <button key={role} onClick={() => setActiveRole(role)} className={`flex-1 rounded-lg px-2 py-2 text-xs font-semibold transition ${activeRole === role ? 'bg-white text-black' : 'text-white/55 hover:bg-white/10'}`}>
                {role === 'Wicketkeeper' ? 'WK' : role === 'Batter' ? 'BAT' : role === 'AllRounder' ? 'AR' : 'BALL'}
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
            {(showPlayerSearch && normalizedPlayerSearch ? playerSearchResults : visibleRolePlayers).map((player) => {
              const isSelected = selected.has(player.id);
              return (
                <div
                  key={player.id}
                  onClick={() => togglePlayer(player.id)}
                  className={`relative cursor-pointer rounded-2xl border p-4 text-left transition ${openHistoryPlayerId === player.id ? 'z-40' : 'z-10'} ${isSelected ? 'border-blue-400/60 bg-blue-500/15' : 'border-white/10 bg-white/5 hover:bg-white/10'}`}
                >
                  <div className="flex items-start gap-3">
                    <PlayerHistoryToggle
                      player={player}
                      isOpen={openHistoryPlayerId === player.id}
                      isSelected={isSelected}
                      onToggle={() => setOpenHistoryPlayerId((current) => (current === player.id ? null : player.id))}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold text-white">{player.name}</p>
                      <p className="text-xs text-white/40">{player.team} | {player.role}</p>
                    </div>
                    <span className={`rounded-lg px-2 py-1 text-xs font-bold ${isSelected ? 'bg-blue-400 text-black' : 'bg-white/10 text-white/40'}`}>
                      {isSelected ? 'Selected' : '+'}
                    </span>
                  </div>
                  <p className="mt-3 text-xs text-white/55">{statText(player)}</p>
                </div>
              );
            })}
            {showPlayerSearch && normalizedPlayerSearch && playerSearchResults.length === 0 && (
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-8 text-center text-sm text-white/40 sm:col-span-2">
                No players found.
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
