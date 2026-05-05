import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useParams, Link, useSearchParams } from 'react-router-dom';
import client from '../api/client';
import { useAuth } from '../auth/AuthContext';
import type { PlayerScore, ContestantScore } from '../types';
import { getTeamTheme } from '../utils/teamTheme';
import RankShiftBadge from '../components/RankShiftBadge';
import { ScoresSkeleton } from '../components/Skeleton';
import { useAppClock } from '../hooks/useAppClock';

interface TeamDiffEntry {
  player_id: number;
  name: string;
  team: string;
  role: string;
  base_points: number;
  multiplier: number;
  tag: string;
  adjusted_points: number;
  is_backup?: boolean;
  replaced_player_id?: number | null;
}

interface TeamDiffRow {
  left: TeamDiffEntry | null;
  right: TeamDiffEntry | null;
  diff_points?: number;
}

interface TeamDiffData {
  current_user: string;
  other_user: string;
  my_total: number;
  other_total: number;
  total_diff: number;
  different_players_diff: number;
  different_players: TeamDiffRow[];
  common_role_diff_total: number;
  common_role_diff: TeamDiffRow[];
  common_players: TeamDiffRow[];
  error?: string;
}

interface Contestant { id: number; name: string; points?: number; rank?: number; }

interface BreakdownPlayer { name: string; team: string; role: string; base_points: number; multiplier: number; tag: string; adjusted_points: number; is_backup?: boolean; replaced_player_id?: number | null; }
interface BackupReplacement {
  backup_player_id: number;
  backup_player_name: string;
  backup_team: string;
  backup_role: string;
  replaced_player_id: number;
  replaced_player_name: string;
}
interface BreakdownData { user_name: string; total: number; players: BreakdownPlayer[]; backup_replacements?: BackupReplacement[]; error?: string; }
interface ScorecardBattingEntry {
  player_id: number;
  name: string;
  dismissal: string;
  is_out: boolean;
  runs: number;
  balls: number;
  fours: number;
  sixes: number;
  strike_rate: number;
}
interface ScorecardBowlingEntry {
  player_id: number;
  name: string;
  overs: number;
  maidens: number;
  runs_conceded: number;
  wickets: number;
  economy: number;
}
interface ScorecardInnings {
  batting_team: string;
  bowling_team: string;
  batting: ScorecardBattingEntry[];
  bowling: ScorecardBowlingEntry[];
  total_runs?: number | null;
  total_wickets?: number | null;
  total_overs?: number | null;
}

type ViewTab = 'scores' | 'scorecard' | 'myteam' | 'diff';

const VIEW_TABS: Array<{ key: ViewTab; label: string }> = [
  { key: 'scores', label: 'Live' },
  { key: 'scorecard', label: 'Scorecard' },
  { key: 'myteam', label: 'My Team' },
  { key: 'diff', label: 'Compare' },
];

const formatRoleName = (role: string) => (role === 'AllRounder' ? 'All Rounder' : role);


export default function ViewScoresPage() {
  const { matchId } = useParams<{ matchId: string }>();
  const [searchParams] = useSearchParams();
  const { profile } = useAuth();
  const { getNow } = useAppClock();
  const [playerScores, setPlayerScores] = useState<PlayerScore[]>([]);
  const [contestants, setContestants] = useState<ContestantScore[]>([]);
  const [scorecard, setScorecard] = useState<ScorecardInnings[]>([]);
  const [myTeam, setMyTeam] = useState<Set<string>>(new Set());
  const [contestantRankChanges, setContestantRankChanges] = useState<Record<number, number>>({});
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [scoresSnapshotVersion, setScoresSnapshotVersion] = useState<number | null>(null);
  const [scoresRefreshing, setScoresRefreshing] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Tab state — read from URL param if present
  const initialTab = (searchParams.get('tab') as ViewTab) || 'scores';
  const [tab, setTab] = useState<ViewTab>(VIEW_TABS.some((entry) => entry.key === initialTab) ? initialTab : 'scores');
  const [expandedPlayer, setExpandedPlayer] = useState<number | null>(null);

  // Team breakdown state
  const [breakdown, setBreakdown] = useState<BreakdownData | null>(null);
  const [breakdownLoading, setBreakdownLoading] = useState(false);
  const [selectedContestantId, setSelectedContestantId] = useState<number | null>(null);
  const [selectedContestantBreakdown, setSelectedContestantBreakdown] = useState<BreakdownData | null>(null);
  const [selectedContestantLoading, setSelectedContestantLoading] = useState(false);
  const [openScorecardIndex, setOpenScorecardIndex] = useState<number>(0);

  // Team diff state
  const [diffContestants, setDiffContestants] = useState<Contestant[]>([]);
  const [selectedOther, setSelectedOther] = useState<number | null>(null);
  const [diffData, setDiffData] = useState<TeamDiffData | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const previousContestantRanksRef = useRef<Record<number, number> | null>(null);

  const isSnapshotConflict = (error: unknown) =>
    Boolean((error as { response?: { status?: number } })?.response?.status === 409);

  const fetchScores = async () => {
    try {
      const [scoresRes, teamRes] = await Promise.all([
        client.get(`/api/scores/${matchId}`),
        client.get(`/api/scores/${matchId}/my-team`).catch(() => ({ data: [] })),
      ]);
      const nextContestants: ContestantScore[] = scoresRes.data.contestants || [];
      const nextRankedContestants = [...nextContestants].sort((a, b) => b.points - a.points);
      const nextRankMap: Record<number, number> = {};
      nextRankedContestants.forEach((entry, i) => {
        let rank = i + 1;
        if (i > 0 && entry.points === nextRankedContestants[i - 1].points) {
          rank = nextRankMap[nextRankedContestants[i - 1].id];
        }
        nextRankMap[entry.id] = rank;
      });

      const previousRankMap = previousContestantRanksRef.current || {};
      const nextRankChanges: Record<number, number> = {};
      Object.entries(nextRankMap).forEach(([idStr, rank]) => {
        const contestantId = Number(idStr);
        const prevRank = previousRankMap[contestantId];
        if (prevRank && prevRank !== rank) {
          nextRankChanges[contestantId] = prevRank - rank;
        }
      });
      previousContestantRanksRef.current = nextRankMap;

      setPlayerScores(scoresRes.data.players || []);
      setContestants(nextContestants);
      setContestantRankChanges(nextRankChanges);
      setScorecard(scoresRes.data.scorecard || []);
      setScoresSnapshotVersion(scoresRes.data.snapshot_version ?? null);
      const team = teamRes.data || [];
      setMyTeam(new Set(team.map((t: string | { player_name: string }) => typeof t === 'string' ? t : t.player_name)));
      setLastUpdated(getNow());
      return scoresRes.data;
    } catch { /* silent */ }
    finally { setLoading(false); }
    return null;
  };

  const fetchBreakdown = async (retry = true, snapshotVersionOverride?: number | null) => {
    setBreakdownLoading(true);
    try {
      const snapshotVersion = snapshotVersionOverride ?? scoresSnapshotVersion;
      const res = await client.get(`/api/scores/${matchId}/team-breakdown`, {
        params: snapshotVersion ? { snapshot_version: snapshotVersion } : undefined,
      });
      setBreakdown(res.data);
    } catch (error) {
      if (retry && isSnapshotConflict(error)) {
        const snapshot = await fetchScores();
        if (snapshot?.snapshot_version) {
          await fetchBreakdown(false, snapshot.snapshot_version);
          return;
        }
      }
      if (!breakdown) {
        setBreakdown(null);
      }
    }
    finally { setBreakdownLoading(false); }
  };

  const fetchContestantBreakdown = async (userId: number, retry = true, snapshotVersionOverride?: number | null) => {
    setSelectedContestantLoading(true);
    try {
      const snapshotVersion = snapshotVersionOverride ?? scoresSnapshotVersion;
      const res = await client.get(`/api/scores/${matchId}/team-breakdown`, {
        params: {
          user_id: userId,
          ...(snapshotVersion ? { snapshot_version: snapshotVersion } : {}),
        },
      });
      setSelectedContestantBreakdown(res.data);
    } catch (error) {
      if (retry && isSnapshotConflict(error)) {
        const snapshot = await fetchScores();
        if (snapshot?.snapshot_version) {
          await fetchContestantBreakdown(userId, false, snapshot.snapshot_version);
          return;
        }
      }
      if (!selectedContestantBreakdown) {
        setSelectedContestantBreakdown(null);
      }
    } finally {
      setSelectedContestantLoading(false);
    }
  };

  const fetchDiffContestants = async (sourceContestants?: ContestantScore[]) => {
    if (sourceContestants && sourceContestants.length > 0) {
      setDiffContestants(sourceContestants.filter((c: Contestant) => c.id !== profile?.id));
      return;
    }
    try {
      const res = await client.get(`/api/scores/${matchId}/contestants`, {
        params: scoresSnapshotVersion ? { snapshot_version: scoresSnapshotVersion } : undefined,
      });
      setDiffContestants(res.data.filter((c: Contestant) => c.id !== profile?.id));
    } catch { /* silent */ }
  };

  const fetchDiff = async (otherId: number, retry = true, snapshotVersionOverride?: number | null) => {
    setDiffLoading(true);
    try {
      const res = await client.get(`/api/scores/${matchId}/team-diff`, {
        params: {
          other_user_id: otherId,
          ...((snapshotVersionOverride ?? scoresSnapshotVersion) ? { snapshot_version: snapshotVersionOverride ?? scoresSnapshotVersion } : {}),
        },
      });
      setDiffData(res.data);
    } catch (error) {
      if (retry && isSnapshotConflict(error)) {
        const snapshot = await fetchScores();
        if (snapshot?.snapshot_version) {
          await fetchDiff(otherId, false, snapshot.snapshot_version);
          return;
        }
      }
      if (!diffData) {
        setDiffData(null);
      }
    }
    finally { setDiffLoading(false); }
  };

  useEffect(() => {
    if (tab !== 'scores') return;
    if (selectedContestantId == null) return;
    if (!scoresSnapshotVersion) return;

    void fetchContestantBreakdown(selectedContestantId, false, scoresSnapshotVersion);
  }, [scoresSnapshotVersion, selectedContestantId, tab]);

  useEffect(() => {
    setLoading(true);
    setPlayerScores([]);
    setContestants([]);
    setScorecard([]);
    setMyTeam(new Set());
    setContestantRankChanges({});
    setLastUpdated(null);
    setScoresSnapshotVersion(null);
    setScoresRefreshing(false);
    setBreakdown(null);
    setDiffData(null);
    setDiffContestants([]);
    setSelectedContestantId(null);
    setSelectedContestantBreakdown(null);
    setOpenScorecardIndex(0);
    setSelectedOther(null);
    previousContestantRanksRef.current = null;
  }, [matchId]);

  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);

    const run = async () => {
      if (tab === 'scores' || tab === 'scorecard') {
        const hasExistingScores = playerScores.length > 0 || contestants.length > 0 || scorecard.length > 0;
        setLoading(!hasExistingScores);
        setScoresRefreshing(hasExistingScores);
        await fetchScores();
        setScoresRefreshing(false);
        intervalRef.current = setInterval(fetchScores, 30000);
      } else if (tab === 'myteam') {
        setLoading(false);
        const snapshot = await fetchScores();
        await fetchBreakdown(true, snapshot?.snapshot_version ?? null);
        intervalRef.current = setInterval(() => fetchBreakdown(true, snapshot?.snapshot_version ?? null), 60000);
      } else if (tab === 'diff') {
        setLoading(false);
        const snapshot = await fetchScores();
        await fetchDiffContestants(snapshot?.contestants || []);
        if (selectedOther) {
          await fetchDiff(selectedOther, true, snapshot?.snapshot_version ?? null);
        }
      }
    };

    run();

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [tab, matchId, selectedOther]);

  useEffect(() => {
    setSelectedContestantId(null);
    setSelectedContestantBreakdown(null);
    setSelectedContestantLoading(false);
  }, [matchId]);

  useEffect(() => {
    const header = document.getElementById('view-scores-sticky-header');
    if (!header) return;

    const updateHeight = () => {
      const height = Math.ceil(header.getBoundingClientRect().height);
      document.documentElement.style.setProperty('--view-scores-sticky-offset', `${height}px`);
    };

    updateHeight();
    const ro = new ResizeObserver(updateHeight);
    ro.observe(header);

    return () => ro.disconnect();
  }, []);

  const sortedContestants = [...contestants].sort((a, b) => b.points - a.points);
  const rankedContestants: (ContestantScore & { rank: number })[] = [];
  sortedContestants.forEach((entry, i) => {
    let rank = i + 1;
    if (i > 0 && entry.points === sortedContestants[i - 1].points) {
      rank = rankedContestants[i - 1].rank;
    }
    rankedContestants.push({ ...entry, rank });
  });

  const selectedContestantSummary = useMemo(() => {
    if (selectedContestantId == null) return null;
    const selectedIndex = rankedContestants.findIndex((contestant) => contestant.id === selectedContestantId);
    if (selectedIndex < 0) return null;

    const selected = rankedContestants[selectedIndex];
    if (selectedIndex === 0) {
      return { rank: selected.rank, diffToAbove: null, diffToFirst: null };
    }

    const above = [...rankedContestants.slice(0, selectedIndex)].reverse().find((contestant) => contestant.points > selected.points) ?? null;
    const first = rankedContestants[0];

    return {
      rank: selected.rank,
      diffToAbove: above ? selected.points - above.points : null,
      diffToFirst: selected.points - first.points,
    };
  }, [rankedContestants, selectedContestantId]);

  if (loading) {
    return (
      <div className="min-h-screen bg-black">
        <header id="view-scores-sticky-header" className="mobile-safe-blur sticky top-[56px] z-30 bg-black/80 border-b border-white/10 md:backdrop-blur-lg">
          <div className="max-w-6xl mx-auto flex items-center justify-between gap-3 px-4 py-4">
            <div className="flex min-w-0 items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-white/10 animate-pulse" />
              <div className="space-y-1.5">
                <div className="h-5 w-28 rounded bg-white/10 animate-pulse" />
                <div className="h-3 w-20 rounded bg-white/10 animate-pulse" />
              </div>
            </div>
            <div className="shrink-0 grid w-[10.5rem] grid-cols-2 gap-1 rounded-xl bg-white/5 p-1">
              <div className="h-7 w-24 rounded-lg bg-white/10 animate-pulse" />
              <div className="h-7 w-24 rounded-lg bg-white/10 animate-pulse" />
              <div className="h-7 w-24 rounded-lg bg-white/10 animate-pulse" />
              <div className="h-7 w-24 rounded-lg bg-white/10 animate-pulse" />
            </div>
          </div>
        </header>
        <main className="max-w-6xl mx-auto px-4 py-6">
          <ScoresSkeleton />
        </main>
      </div>
    );
  }

  const renderPlayerEntry = (entry: TeamDiffEntry | null, side: 'left' | 'right') => {
    if (!entry) return <div className="flex-1 p-3 bg-white/5 rounded-xl text-center text-white/30 text-xs">—</div>;
    const tagColor = entry.tag === 'C' ? 'bg-amber-500' : entry.tag === 'VC' ? 'bg-white/30' : '';
    const theme = getTeamTheme(entry.team);
    return (
      <div className={`flex-1 rounded-xl border p-3 bg-gradient-to-r ${theme.tintClass} ${side === 'left' ? 'border-white/20' : 'border-red-500/20'}`}>
        <div className="flex items-center justify-between mb-1">
          <span className="flex items-center gap-1.5 min-w-0">
            {renderBackupDot(entry.is_backup)}
            <span className="text-white text-sm font-medium truncate">{entry.name}</span>
          </span>
          {entry.tag && <span className={`text-[10px] text-white font-bold px-1.5 py-0.5 rounded ${tagColor}`}>{entry.tag}</span>}
        </div>
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-2 text-white/40">
            {renderTeamBadge(entry.team, true)}
            <span>{getShortRole(entry.role)}</span>
          </div>
          <span className="text-blue-400 font-bold">{entry.adjusted_points} pts</span>
        </div>
        {entry.multiplier > 1 && (
          <div className="text-[10px] text-white/30 mt-0.5">{entry.base_points} &times; {entry.multiplier}</div>
        )}
      </div>
    );
  };

  const getShortRole = (role: string) => {
    if (role === 'Batter') return 'Bat';
    if (role === 'Bowler') return 'Bowl';
    if (role === 'AllRounder') return 'AR';
    if (role === 'Wicketkeeper') return 'WK';
    return role;
  };

  const renderBackupDot = (isBackup?: boolean) =>
    isBackup ? (
      <span
        className="inline-block h-2 w-2 flex-shrink-0 rounded-full bg-sky-400"
        title="Backup replacement"
      />
    ) : null;

  const renderReplacementArrow = (direction: 'out' | 'in') => (
    <span
      className={`inline-flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-bold ${
        direction === 'out'
          ? 'border-red-400/30 bg-red-500/15 text-red-200'
          : 'border-green-400/30 bg-green-500/15 text-green-200'
      }`}
      title={direction === 'out' ? 'Player went out' : 'Player came in'}
    >
      {direction === 'out' ? '↘' : '↗'}
    </span>
  );

  const renderBackupReplacements = (replacements?: BackupReplacement[]) => {
    if (!replacements?.length) return null;

    return (
      <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-3">
        <div className="mb-2 flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-white">Backup Replacement</h3>
            <p className="text-[10px] text-white/35">Who went out and who came in</p>
          </div>
          <span className="rounded-full border border-sky-400/20 bg-sky-500/10 px-2 py-0.5 text-[10px] font-semibold text-sky-300">
            {replacements.length}
          </span>
        </div>
        <div className="space-y-2">
          {replacements.map((replacement) => (
            <div key={`${replacement.backup_player_id}-${replacement.replaced_player_id}`} className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="inline-flex items-center gap-1.5 text-red-200">
                  {renderReplacementArrow('out')}
                  <span className="max-w-[12rem] truncate font-medium">{replacement.replaced_player_name}</span>
                </span>
                <span className="text-white/30">→</span>
                <span className="inline-flex items-center gap-1.5 text-green-200">
                  {renderReplacementArrow('in')}
                  <span className="max-w-[12rem] truncate font-medium">{replacement.backup_player_name}</span>
                </span>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10px] text-white/40">
                {renderTeamBadge(replacement.backup_team, true)}
                <span>{formatRoleName(replacement.backup_role)}</span>
                <span className="text-white/25">Backup applied</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderRoleSymbol = (role: string) => {
    const config = { symbol: getShortRole(role), label: role };
    return (
      <span
        title={formatRoleName(config.label)}
        className="inline-flex min-w-[2.75rem] justify-center rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[11px] font-semibold text-white/70"
      >
        {config.symbol}
      </span>
    );
  };

  const renderOwnerChip = (owner: { id: number; name: string; tag?: string }, compact = false) => (
    <span
      key={`${owner.id}-${owner.name}`}
      className={`inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-1 ${compact ? 'text-[10px]' : 'text-[11px]'} text-white/70`}
    >
      <span className="truncate max-w-[7rem]">{owner.name}</span>
      {owner.tag && (
        <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold ${owner.tag === 'C' ? 'bg-amber-500 text-black' : 'bg-sky-500 text-black'}`}>
          {owner.tag}
        </span>
      )}
    </span>
  );

  const renderTeamBadge = (team: string, compact = false) => {
    const theme = getTeamTheme(team);
    return (
      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 font-semibold ${compact ? 'text-[9px]' : 'text-[10px]'} ${theme.badgeClass}`}>
        {theme.label}
      </span>
    );
  };

  const handleContestantClick = (contestantId: number) => {
    if (selectedContestantId === contestantId) {
      setSelectedContestantId(null);
      setSelectedContestantBreakdown(null);
      setSelectedContestantLoading(false);
      return;
    }

    setSelectedContestantId(contestantId);
    fetchContestantBreakdown(contestantId);
  };

  const getSelectedContestantPlayers = () => {
    if (!selectedContestantBreakdown?.players?.length) return [];
    return [...selectedContestantBreakdown.players].sort((a, b) => b.adjusted_points - a.adjusted_points);
  };

  const renderTeamAnalysisBreakdown = (player: BreakdownPlayer, index: number) => {
    const bd = (player as BreakdownPlayer & { breakdown?: { label: string; points: number }[] }).breakdown || [];
    const isOpen = expandedPlayer === 1000 + index;

    return (
      <div key={`${player.name}-${index}`}>
        <div
          onClick={() => setExpandedPlayer(isOpen ? null : 1000 + index)}
          className={`flex items-center px-4 py-3 hover:bg-white/5 transition-colors cursor-pointer bg-gradient-to-r ${getTeamTheme(player.team).tintClass}`}>
          <div className="w-5 text-center flex-shrink-0">
            <span className={`text-[10px] text-white/40 transition-transform inline-block ${isOpen ? 'rotate-90' : ''}`}>&#9654;</span>
          </div>
          <div className="w-7 flex-shrink-0 ml-1">
            {player.tag === 'C' && <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-amber-500 text-black text-[10px] font-bold">C</span>}
            {player.tag === 'VC' && <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-sky-500 text-black text-[10px] font-bold">VC</span>}
          </div>
          <div className="min-w-0 flex-[1.35] ml-2">
            <div className="flex items-center gap-2">
              {renderBackupDot(player.is_backup)}
              <p className="text-white text-sm font-medium truncate">{player.name}</p>
            </div>
            <div className="mt-1 flex items-center gap-2 text-xs text-white/40">
              {renderTeamBadge(player.team)}
              <span>{getShortRole(player.role)}</span>
            </div>
          </div>
          <div className="text-right flex-shrink-0 ml-2 min-w-[56px]">
            <p className="text-blue-400 font-bold text-sm">{player.adjusted_points}</p>
            {player.multiplier > 1 && (
              <p className="text-white/30 text-[10px]">{player.base_points} &times; {player.multiplier}</p>
            )}
          </div>
        </div>
        {isOpen && bd.length > 0 && (
          <div className="px-4 pb-3 pt-1">
            <p className="text-white/30 text-[10px] uppercase tracking-wider mb-1.5">Player Analysis</p>
            <div className="flex flex-wrap gap-1.5">
              {bd.map((item: { label: string; points: number }, j: number) => (
                <span key={j} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium border ${
                  item.points > 0 ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'
                }`}>
                  {item.label} <span className="font-bold">{item.points > 0 ? '+' : ''}{item.points}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderLiveSelectedContestant = () => {
    if (!selectedContestantBreakdown) return null;
    const players = getSelectedContestantPlayers();
    if (!players.length) return null;
    const renderPlayerCard = (player: BreakdownPlayer, index: number) => {
      return (
        <div key={`${player.name}-${index}`} className={`rounded-xl border border-white/10 bg-gradient-to-r ${getTeamTheme(player.team).tintClass} px-2.5 py-2`}>
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                {renderBackupDot(player.is_backup)}
                <p className="truncate text-[13px] font-medium text-white">{player.name}</p>
                {player.tag && (
                  <span className={`inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1.5 text-[9px] font-bold ${
                    player.tag === 'C' ? 'bg-amber-500 text-black' : 'bg-sky-500 text-black'
                  }`}>
                    {player.tag}
                  </span>
                )}
              </div>
              <div className="mt-1 flex items-center gap-1.5 text-[11px] text-white/40">
                {renderTeamBadge(player.team, true)}
                <span className="truncate">{formatRoleName(player.role)}</span>
              </div>
            </div>
            <div className="text-right shrink-0">
              <p className="text-sm font-bold text-blue-400">{player.adjusted_points}</p>
              <p className="text-[10px] text-white/30">Pts</p>
            </div>
          </div>
          {player.is_backup && <div className="mt-1.5 text-[10px] text-sky-300">Backup</div>}
        </div>
      );
    };

    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2">
          {players.map((player, index) => renderPlayerCard(player, index))}
        </div>
      </div>
    );
  };

  const renderScorecardSection = (innings: ScorecardInnings, index: number) => {
    const battingRows = innings.batting || [];
    const bowlingRows = innings.bowling || [];
    const battingRuns = innings.total_runs ?? battingRows.reduce((sum, player) => sum + (player.runs || 0), 0);
    const wicketsLost = innings.total_wickets ?? battingRows.filter((player) => player.is_out).length;
    const bowlingOvers = innings.total_overs ?? bowlingRows.reduce((sum, player) => sum + (player.overs || 0), 0);
    const isOpen = openScorecardIndex === index;

    return (
      <div key={`${innings.batting_team}-${index}`} className="overflow-hidden rounded-2xl border border-white/10 bg-white/5">
        <button
          type="button"
          onClick={() => setOpenScorecardIndex(isOpen ? -1 : index)}
          className="flex w-full items-center justify-between gap-3 bg-white/[0.03] px-4 py-3 text-left"
        >
          <div className="flex min-w-0 items-center gap-2">
            <span className={`text-[10px] text-white/45 transition-transform ${isOpen ? 'rotate-90' : ''}`}>&#9654;</span>
            {renderTeamBadge(innings.batting_team)}
            <h2 className="truncate text-sm font-semibold text-white">{innings.batting_team}</h2>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-base font-bold text-white">{battingRuns}/{wicketsLost}</div>
            <div className="text-[11px] text-white/40">{bowlingOvers.toFixed(1)} ov</div>
          </div>
        </button>

        {isOpen && (
        <div className="space-y-4 border-t border-white/10 px-4 py-4">
          <div>
            <div className="mb-2 flex items-center justify-between gap-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-white/45">
              <h3>Batting</h3>
              <div className="shrink-0 font-mono">
                <div className="flex items-center justify-end gap-3">
                  <span className="w-7 text-right">R</span>
                  <span className="w-7 text-right">B</span>
                  <span className="w-7 text-right">4s</span>
                  <span className="w-7 text-right">6s</span>
                  <span className="w-10 text-right">SR</span>
                </div>
              </div>
            </div>
            <div className="space-y-2">
              {battingRows.length === 0 ? (
                <div className="py-4 text-center text-sm text-white/35">No batting data yet.</div>
              ) : (
                battingRows.map((player) => (
                  <div key={`bat-${innings.batting_team}-${player.player_id}`} className="flex items-start justify-between gap-3 border-b border-white/5 pb-2 last:border-b-0">
                    <div className="min-w-0">
                      <div className="text-sm font-medium leading-snug text-white break-words">{player.name}</div>
                      <div className="mt-0.5 text-[11px] text-white/35">{player.dismissal}</div>
                    </div>
                    <div className="shrink-0 font-mono text-[12px] leading-5 text-white/75">
                      <div className="flex items-center justify-end gap-3">
                        <span className="w-7 text-right font-semibold text-white">{player.runs}</span>
                        <span className="w-7 text-right">{player.balls}</span>
                        <span className="w-7 text-right">{player.fours}</span>
                        <span className="w-7 text-right">{player.sixes}</span>
                        <span className="w-10 text-right">{player.strike_rate?.toFixed(1)}</span>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between gap-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-white/45">
              <h3>
                Bowling {innings.bowling_team ? `• ${getTeamTheme(innings.bowling_team).label}` : ''}
              </h3>
              <div className="shrink-0 font-mono">
                <div className="flex items-center justify-end gap-3">
                  <span className="w-7 text-right">O</span>
                  <span className="w-7 text-right">M</span>
                  <span className="w-7 text-right">R</span>
                  <span className="w-7 text-right">W</span>
                  <span className="w-10 text-right">ER</span>
                </div>
              </div>
            </div>
            <div className="space-y-2">
              {bowlingRows.length === 0 ? (
                <div className="py-4 text-center text-sm text-white/35">No bowling data yet.</div>
              ) : (
                bowlingRows.map((player) => (
                  <div key={`bowl-${innings.batting_team}-${player.player_id}`} className="flex items-start justify-between gap-3 border-b border-white/5 pb-2 last:border-b-0">
                    <div className="min-w-0">
                      <div className="text-sm font-medium leading-snug text-white break-words">{player.name}</div>
                    </div>
                    <div className="shrink-0 font-mono text-[12px] leading-5 text-white/75">
                      <div className="flex items-center justify-end gap-3">
                        <span className="w-7 text-right">{player.overs}</span>
                        <span className="w-7 text-right">{player.maidens}</span>
                        <span className="w-7 text-right">{player.runs_conceded}</span>
                        <span className="w-7 text-right font-semibold text-white">{player.wickets}</span>
                        <span className="w-10 text-right">{player.economy?.toFixed(1)}</span>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
        )}
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-black">
      {/* Header */}
        <header id="view-scores-sticky-header" className="mobile-safe-blur sticky top-[56px] z-30 bg-black/80 border-b border-white/10 md:backdrop-blur-lg">
        <div className="max-w-6xl mx-auto flex items-center justify-between gap-3 px-4 py-4">
          <div className="flex min-w-0 items-center gap-3">
            <Link to="/dashboard" className="p-2 hover:bg-white/10 rounded-xl transition-all">
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </Link>
            <div className="min-w-0">
              <h1 className="text-lg font-bold text-white">Match #{matchId}</h1>
              {lastUpdated && <p className="text-xs text-white/40">Updated {lastUpdated.toLocaleTimeString()}</p>}
            </div>
          </div>
          <div className="shrink-0 grid w-[10.5rem] grid-cols-2 gap-1 rounded-xl bg-white/5 p-1">
              {VIEW_TABS.map((entry) => (
                <button
                  key={entry.key}
                  onClick={() => setTab(entry.key)}
                  className={`w-full whitespace-nowrap rounded-lg px-2 py-1 text-[11px] font-medium transition ${tab === entry.key ? 'bg-white text-black' : 'text-white/50 hover:text-white'}`}
                >
                  {entry.label}
                </button>
              ))}
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6 space-y-6">

        {tab === 'scores' && (
          <>
            {/* Auto-refresh */}
            <div className="flex items-center gap-2 text-xs text-white/40">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500" />
              </span>
              Auto-refreshes every 30s
              {scoresRefreshing && (
                <>
                  <span className="text-white/25">•</span>
                  <span className="text-white/35">Refreshing latest snapshot...</span>
                </>
              )}
            </div>

            {/* Contestant Rankings */}
            <div className="max-w-2xl bg-white/5 border border-white/10 rounded-2xl overflow-hidden">
              <div className="px-4 py-3 border-b border-white/10">
                <h2 className="text-white font-semibold">Contestant Rankings</h2>
              </div>
              <div className="divide-y divide-white/5">
                {sortedContestants.length === 0 ? (
                  <div className="px-4 py-8 text-center text-white/40">No contestant scores yet.</div>
                ) : (
                  rankedContestants.map((c) => {
                    const isSelected = selectedContestantId === c.id;
                    const isCurrentUser = c.id === profile?.id;
                    // Show bonus winner badge only if prediction_bonus > 0 (actual winner).
                    // For non-winners, show tier label as a soft indicator (no bonus amount).
                    const wonBonus = c.prediction_bonus != null && c.prediction_bonus > 0;
                    const predictionBadgeLabel = wonBonus
                      ? (c.prediction_label || c.prediction_tier_label)
                      : (c.prediction_tier_label || null);
                    const predictionBadgeBonus = wonBonus ? c.prediction_bonus! : 0;
                    return (
                      <div key={c.id}>
                        <button
                          type="button"
                          onClick={() => handleContestantClick(c.id)}
                          className={`flex w-full items-center px-4 py-3 text-left transition-colors ${
                            isSelected ? 'bg-white/8' : isCurrentUser ? 'bg-amber-500/10 hover:bg-amber-500/15' : 'hover:bg-white/5'
                          }`}
                        >
                          <div className="w-8 flex-shrink-0 text-center">
                            {c.rank === 1 ? <span className="text-lg">&#x1F947;</span>
                              : c.rank === 2 ? <span className="text-lg">&#x1F948;</span>
                              : c.rank === 3 ? <span className="text-lg">&#x1F949;</span>
                              : <span className="text-white/40 text-sm font-medium">{c.rank}</span>}
                          </div>
                          <div className="ml-3 min-w-0 flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-white font-medium text-sm">{c.name}</span>
                              {isCurrentUser && (
                                <span className="inline-flex items-center rounded-full bg-amber-400/20 px-2 py-0.5 text-[10px] font-semibold text-amber-300">
                                  You
                                </span>
                              )}
                              {predictionBadgeLabel && (
                                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold ${
                                  predictionBadgeBonus >= 500
                                    ? 'bg-amber-500/15 text-amber-300 border border-amber-500/25'
                                    : predictionBadgeBonus >= 200
                                    ? 'bg-orange-500/15 text-orange-300 border border-orange-500/25'
                                    : 'bg-blue-500/15 text-blue-300 border border-blue-500/25'
                                }`}>
                                  🎯 {predictionBadgeLabel}
                                </span>
                              )}
                            </div>
                            {c.predicted_points != null && (
                              <p className="text-[10px] text-white/35 mt-0.5">
                                Predicted: {c.predicted_points} pts
                              </p>
                            )}
                          </div>
                          <div className="ml-3 flex shrink-0 items-center gap-1.5">
                            <RankShiftBadge delta={contestantRankChanges[c.id] ?? undefined} compact />
                            <span className="text-blue-400 font-bold text-sm whitespace-nowrap">{c.points} pts</span>
                            {(c.prediction_bonus != null && c.prediction_bonus > 0) && (
                              <span className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-bold ${
                                c.prediction_bonus >= 500 ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                                  : c.prediction_bonus >= 200 ? 'bg-orange-500/20 text-orange-300 border border-orange-500/30'
                                  : 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                              }`}>
                                🎯+{c.prediction_bonus}
                              </span>
                            )}
                          </div>
                          <span className={`ml-3 text-[10px] text-white/40 transition-transform ${isSelected ? 'rotate-90' : ''}`}>&#9654;</span>
                        </button>

                        {isSelected && (
                          <div className="border-t border-white/5 bg-black/20 px-4 py-4">
                            {selectedContestantLoading && !selectedContestantBreakdown ? (
                              <div className="flex items-center justify-center py-4">
                                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-white" />
                              </div>
                            ) : selectedContestantBreakdown?.error ? (
                              <p className="text-sm text-white/40">{selectedContestantBreakdown.error}</p>
                            ) : selectedContestantBreakdown ? (
                              <div className="space-y-3">
                                <div className="flex items-start justify-between gap-3">
                                  <div className="min-w-0">
                                    <p className="text-xs uppercase tracking-[0.2em] text-white/35">Team View</p>
                                    <div className="flex items-center gap-2">
                                      <h3 className="truncate text-sm font-semibold text-white">{selectedContestantBreakdown.user_name}</h3>
                                      {selectedContestantSummary && (
                                        <span className="inline-flex items-center rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold text-white/70">
                                          #{selectedContestantSummary.rank}
                                        </span>
                                      )}
                                    </div>
                                  </div>
                                  <div className="text-right">
                                    <p className="text-sm font-bold text-blue-400">{selectedContestantBreakdown.total} pts</p>
                                    {selectedContestantSummary?.rank === 1 && (
                                      <p className="text-[10px] uppercase tracking-[0.2em] text-white/30">Top rank</p>
                                    )}
                                  </div>
                                </div>
                                {selectedContestantSummary?.rank && selectedContestantSummary.rank > 1 && (
                                  <div className="grid grid-cols-2 gap-2 rounded-xl border border-white/10 bg-white/[0.03] p-2">
                                    <div className="rounded-lg bg-black/30 px-2 py-1.5">
                                      <p className="text-[9px] uppercase tracking-[0.16em] text-white/30">Vs Above</p>
                                      {selectedContestantSummary.diffToAbove == null ? (
                                        <p className="text-xs font-bold text-white/40">—</p>
                                      ) : (
                                        <p className={`text-xs font-bold ${selectedContestantSummary.diffToAbove < 0 ? 'text-red-300' : 'text-green-300'}`}>
                                          {selectedContestantSummary.diffToAbove > 0 ? '+' : ''}{selectedContestantSummary.diffToAbove.toFixed(2)}
                                        </p>
                                      )}
                                    </div>
                                    <div className="rounded-lg bg-black/30 px-2 py-1.5">
                                      <p className="text-[9px] uppercase tracking-[0.16em] text-white/30">Vs #1</p>
                                      {(() => {
                                        const diffToFirst = selectedContestantSummary.diffToFirst ?? 0;
                                        return (
                                          <p className={`text-xs font-bold ${diffToFirst < 0 ? 'text-red-300' : 'text-green-300'}`}>
                                            {diffToFirst > 0 ? '+' : ''}{diffToFirst.toFixed(2)}
                                          </p>
                                        );
                                      })()}
                                    </div>
                                  </div>
                                )}
                                {selectedContestantLoading && (
                                  <p className="text-[10px] uppercase tracking-[0.2em] text-white/30">Refreshing latest data...</p>
                                )}
                                {renderLiveSelectedContestant()}
                                {renderBackupReplacements(selectedContestantBreakdown.backup_replacements)}
                              </div>
                            ) : (
                              <p className="text-sm text-white/40">No team data available.</p>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            {/* Player Stats — Mobile: card view, Desktop: table */}
            <div className="bg-white/5 border border-white/10 rounded-2xl overflow-hidden">
              <div className="px-4 py-3 border-b border-white/10">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <h2 className="text-white font-semibold">Player Statistics</h2>
                  <span className="text-[11px] text-white/40">Tap player for details</span>
                </div>
              </div>

              {playerScores.length === 0 ? (
                <div className="px-4 py-8 text-center text-white/40">No scores available yet.</div>
              ) : (
                <>
                  {/* Mobile card view */}
                  <div className="md:hidden divide-y divide-white/5">
                    {playerScores.map((p, i) => {
                      const isMyPlayer = myTeam.has(p.name);
                      const isExpanded = expandedPlayer === i;
                      const bd = (p as any).breakdown || [];
                      const owners = p.owners || [];
                      const hasBatting = p.runs > 0 || p.balls > 0;
                      const hasBowling = p.overs > 0;
                      const hasFielding = p.catches > 0 || p.stumpings > 0 || p.runout_direct > 0 || p.runout_indirect > 0;
                      return (
                        <div key={i}>
                          <div
                            onClick={() => setExpandedPlayer(isExpanded ? null : i)}
                            className={`px-4 py-3 cursor-pointer transition-colors ${isMyPlayer ? 'player-selected-highlight' : `bg-gradient-to-r ${getTeamTheme(p.team).tintClass} hover:bg-white/5`}`}
                          >
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2 min-w-0">
                                <span className={`text-[10px] text-white/40 transition-transform ${isExpanded ? 'rotate-90' : ''}`}>&#9654;</span>
                                {renderTeamBadge(p.team, true)}
                                <span className="text-white font-medium text-sm truncate">{p.name}</span>
                                {isMyPlayer && <span className="w-1.5 h-1.5 bg-lime-400 rounded-full flex-shrink-0" />}
                              </div>
                              <div className="flex items-center gap-2 flex-shrink-0">
                                {renderRoleSymbol(p.role)}
                                <span className="text-blue-400 font-bold text-sm min-w-[3rem] text-right">{p.points} pts</span>
                              </div>
                            </div>

                            {/* Compact stats row */}
                            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-white/50">
                              {hasBatting && (
                                <span>{p.runs}/{p.balls}b {p.fours > 0 && `${p.fours}x4 `}{p.sixes > 0 && `${p.sixes}x6 `}SR {p.strike_rate?.toFixed(0)}</span>
                              )}
                              {hasBowling && (
                                <span>{p.wickets}W {p.overs}ov {p.runs_conceded}rc Econ {p.economy?.toFixed(1)}</span>
                              )}
                              {hasFielding && (
                                <span>
                                  {p.catches > 0 && `${p.catches}ct `}
                                  {p.stumpings > 0 && `${p.stumpings}st `}
                                  {p.runout_direct > 0 && `${p.runout_direct}ro `}
                                  {p.runout_indirect > 0 && `${p.runout_indirect}ro-i`}
                                </span>
                              )}
                              {!hasBatting && !hasBowling && !hasFielding && <span>{p.played ? 'Played' : 'DNP'}</span>}
                            </div>
                          </div>

                          {/* Expanded breakdown */}
                          {isExpanded && (
                            <div className="px-4 py-3 border-t border-white/10 bg-black shadow-inner shadow-black/20">
                              <p className="text-white/40 text-[10px] uppercase tracking-wider mb-2">Analysis</p>

                              {/* Full stat grid */}
                              <div className="grid grid-cols-3 gap-x-4 gap-y-1 text-xs mb-3">
                                {hasBatting && <>
                                  <div className="text-white/40">Runs</div><div className="text-white font-medium">{p.runs} ({p.balls}b)</div><div className="text-white/40">SR {p.strike_rate?.toFixed(1)}</div>
                                  <div className="text-white/40">Fours</div><div className="text-white font-medium">{p.fours}</div><div />
                                  <div className="text-white/40">Sixes</div><div className="text-white font-medium">{p.sixes}</div><div />
                                </>}
                                {hasBowling && <>
                                  <div className="text-white/40">Wickets</div><div className="text-white font-medium">{p.wickets}</div><div className="text-white/40">Econ {p.economy?.toFixed(1)}</div>
                                  <div className="text-white/40">Overs</div><div className="text-white font-medium">{p.overs}</div><div className="text-white/40">{p.maidens}mdn {p.dot_balls}dot</div>
                                </>}
                                {hasFielding && <>
                                  <div className="text-white/40">Catches</div><div className="text-white font-medium">{p.catches}</div><div />
                                  {p.stumpings > 0 && <><div className="text-white/40">Stumpings</div><div className="text-white font-medium">{p.stumpings}</div><div /></>}
                                  {(p.runout_direct > 0 || p.runout_indirect > 0) && <><div className="text-white/40">Run-outs</div><div className="text-white font-medium">{p.runout_direct}d / {p.runout_indirect}i</div><div /></>}
                                </>}
                              </div>

                              {bd.length > 0 && (
                                <div className="flex flex-wrap gap-1.5 rounded-2xl border border-white/10 bg-black p-3">
                                  {bd.map((item: { label: string; points: number }, j: number) => (
                                    <span key={j}
                                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium border ${
                                        item.points > 0 ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'
                                      }`}>
                                      {item.label} <span className="font-bold">{item.points > 0 ? '+' : ''}{item.points}</span>
                                    </span>
                                  ))}
                                  <span className="inline-flex items-center gap-1 rounded-md border border-blue-500/20 bg-blue-500/10 px-2 py-0.5 text-[11px] font-bold text-blue-400">
                                    Total: {p.points}
                                  </span>
                                </div>
                              )}
                              {owners.length > 0 && (
                                <div className="mt-3">
                                  <p className="mb-1.5 text-white/30 text-[10px] uppercase tracking-wider">Picked By</p>
                                  <div className="flex flex-wrap gap-1.5">
                                    {owners.map((owner) => renderOwnerChip(owner, true))}
                                  </div>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {/* Desktop table view */}
                  <div className="hidden md:block max-h-[72vh] overflow-auto">
                    <table className="min-w-[1600px] w-full text-sm">
                      <thead>
                        <tr className="bg-white/5 text-white/50 text-xs uppercase tracking-wider">
                          <th className="sticky top-0 left-0 z-20 min-w-[220px] border-r border-white/10 bg-black px-4 py-3 text-left font-medium shadow-[10px_0_18px_-12px_rgba(15,23,42,0.95)]">Player</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">Pts</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-left font-medium">Team</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-center font-medium">Role</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-center font-medium">P</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-center font-medium">Out</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">Runs</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">Balls</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">4s</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">6s</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">SR</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">Overs</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">Mdns</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">Runs Ag</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">Wkts</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">Dots</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">Econ</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">Ct</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">St</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">RO-D</th>
                          <th className="sticky top-0 bg-black px-3 py-3 text-right font-medium">RO-I</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {playerScores.map((p, i) => {
                          const isMyPlayer = myTeam.has(p.name);
                          const isExpanded = expandedPlayer === i;
                          const bd = (p as any).breakdown || [];
                          const owners = p.owners || [];
                          return (
                            <React.Fragment key={i}>
                              <tr
                                onClick={() => setExpandedPlayer(isExpanded ? null : i)}
                                className={`cursor-pointer transition-colors ${isMyPlayer ? 'player-selected-highlight' : `bg-gradient-to-r ${getTeamTheme(p.team).tintClass} hover:bg-white/5`}`}>
                                <td className="sticky left-0 z-10 min-w-[220px] border-r border-white/10 px-4 py-2.5 text-white font-medium whitespace-nowrap shadow-[10px_0_18px_-12px_rgba(15,23,42,0.95)] bg-black">
                                  <span className={`inline-block w-3 text-[10px] text-white/40 mr-1 transition-transform ${isExpanded ? 'rotate-90' : ''}`}>&#9654;</span>
                                  {p.name}
                                  {isMyPlayer && <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-lime-400" />}
                                </td>
                                <td className="px-3 py-2.5 text-right font-bold text-blue-400">{p.points}</td>
                                <td className="px-3 py-2.5 text-white/50">{renderTeamBadge(p.team)}</td>
                                <td className="px-3 py-2.5 text-center">{renderRoleSymbol(p.role)}</td>
                                <td className="px-3 py-2.5 text-center text-white">{p.played ? 'Y' : 'N'}</td>
                                <td className="px-3 py-2.5 text-center text-white">{p.is_out ? 'Y' : 'N'}</td>
                                <td className="px-3 py-2.5 text-right text-white">{p.runs}</td>
                                <td className="px-3 py-2.5 text-right text-white/50">{p.balls}</td>
                                <td className="px-3 py-2.5 text-right text-white/50">{p.fours}</td>
                                <td className="px-3 py-2.5 text-right text-white/50">{p.sixes}</td>
                                <td className="px-3 py-2.5 text-right text-white/50">{p.strike_rate?.toFixed(1)}</td>
                                <td className="px-3 py-2.5 text-right text-white/50">{p.overs}</td>
                                <td className="px-3 py-2.5 text-right text-white/50">{p.maidens}</td>
                                <td className="px-3 py-2.5 text-right text-white/50">{p.runs_conceded}</td>
                                <td className="px-3 py-2.5 text-right text-white">{p.wickets}</td>
                                <td className="px-3 py-2.5 text-right text-white/50">{p.dot_balls}</td>
                                <td className="px-3 py-2.5 text-right text-white/50">{p.economy?.toFixed(1)}</td>
                                <td className="px-3 py-2.5 text-right text-white/50">{p.catches}</td>
                                <td className="px-3 py-2.5 text-right text-white/50">{p.stumpings}</td>
                                <td className="px-3 py-2.5 text-right text-white/50">{p.runout_direct}</td>
                                <td className="px-3 py-2.5 text-right text-white/50">{p.runout_indirect}</td>
                              </tr>
                              {isExpanded && (
                              <tr className="bg-black">
                                <td colSpan={21} className="px-4 py-3">
                                  <p className="text-white/40 text-[10px] uppercase tracking-wider mb-2">Player Analysis</p>
                                  {bd.length > 0 && (
                                      <div className="flex flex-wrap gap-2 rounded-2xl border border-white/10 bg-black p-3 shadow-inner shadow-black/20">
                                        {bd.map((item: { label: string; points: number }, j: number) => (
                                          <span key={j}
                                            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium border ${
                                              item.points > 0 ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'
                                            }`}>
                                            {item.label}
                                            <span className="font-bold">{item.points > 0 ? '+' : ''}{item.points}</span>
                                          </span>
                                        ))}
                                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold bg-white/10 text-white border border-white/20">
                                          Total: {p.points}
                                        </span>
                                      </div>
                                    )}
                                    {owners.length > 0 && (
                                      <div className={`${bd.length > 0 ? 'mt-3' : ''}`}>
                                        <p className="mb-2 text-white/30 text-[10px] uppercase tracking-wider">Picked By</p>
                                        <div className="flex flex-wrap gap-2">
                                          {owners.map((owner) => renderOwnerChip(owner))}
                                        </div>
                                      </div>
                                    )}
                                  </td>
                                </tr>
                              )}
                            </React.Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>

          </>
        )}

        {tab === 'scorecard' && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-xs text-white/40">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-sky-500" />
              </span>
              Reuses live score data and refreshes every 30s
              {scoresRefreshing && (
                <>
                  <span className="text-white/25">•</span>
                  <span className="text-white/35">Refreshing latest snapshot...</span>
                </>
              )}
            </div>

            {scorecard.length === 0 ? (
              <div className="bg-white/5 border border-white/10 rounded-2xl p-6 text-center text-white/40">
                No scorecard data available yet.
              </div>
            ) : (
              scorecard.map((innings, index) => renderScorecardSection(innings, index))
            )}
          </div>
        )}

        {tab === 'myteam' && (
          <div className="space-y-4">
            {breakdownLoading && !breakdown ? (
              <div className="flex justify-center py-12">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white" />
              </div>
            ) : breakdown?.error ? (
              <div className="bg-white/5 border border-white/10 rounded-2xl p-6 text-center text-white/40">
                {breakdown.error}
              </div>
            ) : breakdown ? (
              <>
                {breakdownLoading && (
                  <div className="flex items-center gap-2 text-xs text-white/35">
                    <span className="inline-flex h-2 w-2 rounded-full bg-sky-400 animate-pulse" />
                    Refreshing latest team analysis...
                  </div>
                )}
                {/* Ground Preview with Points */}
                <div className="rounded-2xl overflow-hidden shadow-2xl max-w-md mx-auto"
                  style={{ background: 'linear-gradient(180deg, #1a5e1a 0%, #2d8a2d 30%, #3da33d 50%, #2d8a2d 70%, #1a5e1a 100%)' }}>
                  <div className="text-center pt-4 pb-2">
                    <p className="text-blue-400 text-lg font-bold">{breakdown.total} <span className="text-sm text-blue-200/70">pts</span></p>
                    <p className="text-white/40 text-[10px] uppercase tracking-widest">Team Analysis</p>
                  </div>
                  <div className="relative px-4 pb-5">
                    <div className="absolute inset-x-8 inset-y-4 border-2 border-white/15 rounded-[50%]" />
                    {(['Wicketkeeper', 'Batter', 'AllRounder', 'Bowler'] as const).map((role) => {
                      const rolePlayers = breakdown.players.filter(p => p.role === role);
                      if (rolePlayers.length === 0) return null;
                      const roleLabel = role === 'AllRounder' ? 'All Rounders' : role === 'Wicketkeeper' ? 'Wicketkeeper' : role + 's';
                      return (
                        <div key={role} className="relative z-10 mb-3">
                          <p className="text-center text-white/30 text-[9px] uppercase tracking-widest mb-1.5">{roleLabel}</p>
                          <div className="flex justify-center gap-2 flex-wrap">
                            {rolePlayers.map((p, i) => (
                              <div key={i} className="flex flex-col items-center">
                                <div className={`w-10 h-10 rounded-full flex items-center justify-center text-[10px] font-bold shadow-lg ${
                                  p.tag === 'C' ? 'bg-amber-400 text-black ring-2 ring-amber-300' :
                                  p.tag === 'VC' ? 'bg-sky-400 text-black ring-2 ring-sky-300' :
                                  'bg-white text-blue-900'
                                }`}>
                                  {p.tag || p.adjusted_points}
                                </div>
                                <div className="mt-0.5 flex items-center gap-1">
                                  {renderBackupDot(p.is_backup)}
                                  <p className="max-w-[55px] truncate text-center text-[9px] font-medium text-white">{p.name.split(' ').pop()}</p>
                                </div>
                                <p className="text-blue-300 text-[9px] font-bold">{p.adjusted_points}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="flex justify-center gap-4 pb-3 text-[9px] text-white/40">
                    <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-amber-400"></span> C (2x)</span>
                    <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-sky-400"></span> VC (1.5x)</span>
                  </div>
                </div>

                {renderBackupReplacements(breakdown.backup_replacements)}

                <div className="rounded-2xl overflow-hidden bg-white/5 border border-white/10">
                  <div className="px-4 py-3 border-b border-white/10">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <h3 className="text-white font-semibold text-sm">Player Contributions</h3>
                        <p className="text-[10px] text-white/35">Tap player for analysis</p>
                      </div>
                      <p className="text-sm font-bold text-blue-400">{breakdown.total} pts</p>
                    </div>
                  </div>
                  <div className="divide-y divide-white/5">
                    {breakdown.players.map((p, i) => renderTeamAnalysisBreakdown(p, i))}
                  </div>
                </div>
              </>
            ) : (
              <div className="bg-white/5 border border-white/10 rounded-2xl p-6 text-center text-white/40">
                No team data available.
              </div>
            )}
          </div>
        )}

        {tab === 'diff' && (
          <div className="space-y-4">
            {/* Contestant selector */}
            <div className="bg-white/5 border border-white/10 rounded-2xl p-4">
              <h2 className="text-white font-semibold mb-3">Compare Teams</h2>
              {diffContestants.length === 0 ? (
                <p className="text-white/40 text-sm">No other contestants have picked teams for this match yet.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {diffContestants.map((c) => (
                    <button
                      key={c.id}
                      onClick={() => setSelectedOther(c.id)}
                      className={`px-4 py-2 rounded-xl text-sm font-medium transition ${
                        selectedOther === c.id
                          ? 'bg-white text-black'
                          : 'bg-white/10 text-white/50 hover:bg-white/20'
                      }`}
                    >
                      {c.rank ? `#${c.rank} ` : ''}{c.name}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {diffLoading && !diffData && (
              <div className="flex justify-center py-8">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white" />
              </div>
            )}

            {diffData && !diffData.error && (
              <>
                {diffLoading && (
                  <div className="flex items-center gap-2 text-xs text-white/35">
                    <span className="inline-flex h-2 w-2 rounded-full bg-sky-400 animate-pulse" />
                    Refreshing latest comparison...
                  </div>
                )}
                {/* Score summary */}
                <div className="grid grid-cols-3 gap-3">
                  <div className="bg-white/10 border border-white/20 rounded-2xl p-4 text-center">
                    <p className="text-white/50 text-xs font-medium mb-1">You</p>
                    <p className="text-white text-2xl font-bold">{diffData.my_total}</p>
                  </div>
                  <div className={`${diffData.total_diff > 0 ? 'bg-blue-500/10 border-blue-500/20' : diffData.total_diff < 0 ? 'bg-red-500/10 border-red-500/20' : 'bg-white/5 border-white/10'} border rounded-2xl p-4 text-center`}>
                    <p className="text-white/50 text-xs font-medium mb-1">Diff</p>
                    <p className={`text-2xl font-bold ${diffData.total_diff > 0 ? 'text-blue-400' : diffData.total_diff < 0 ? 'text-red-400' : 'text-white'}`}>
                      {diffData.total_diff > 0 ? '+' : ''}{diffData.total_diff}
                    </p>
                  </div>
                  <div className="bg-red-500/10 border border-red-500/20 rounded-2xl p-4 text-center">
                    <p className="text-red-300 text-xs font-medium mb-1">{diffData.other_user}</p>
                    <p className="text-white text-2xl font-bold">{diffData.other_total}</p>
                  </div>
                </div>

                {/* Different players */}
                {diffData.different_players.length > 0 && diffData.different_players.some(r => r.left || r.right) && (
                  <div className="bg-white/5 border border-white/10 rounded-2xl p-4">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-white font-semibold text-sm">Different Players</h3>
                      <span className={`text-xs font-bold px-2 py-1 rounded-full ${diffData.different_players_diff > 0 ? 'bg-blue-500/20 text-blue-400' : diffData.different_players_diff < 0 ? 'bg-red-500/20 text-red-400' : 'bg-white/10 text-white'}`}>
                        {diffData.different_players_diff > 0 ? '+' : ''}{diffData.different_players_diff} pts
                      </span>
                    </div>
                    <div className="space-y-2">
                      {diffData.different_players.map((row, i) => (
                        <div key={i} className="flex gap-2">
                          {renderPlayerEntry(row.left, 'left')}
                          {renderPlayerEntry(row.right, 'right')}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Common players with C/VC diff */}
                {diffData.common_role_diff.length > 0 && (
                  <div className="bg-white/5 border border-white/10 rounded-2xl p-4">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-white font-semibold text-sm">Same Players, Different C/VC</h3>
                      <span className={`text-xs font-bold px-2 py-1 rounded-full ${diffData.common_role_diff_total > 0 ? 'bg-blue-500/20 text-blue-400' : diffData.common_role_diff_total < 0 ? 'bg-red-500/20 text-red-400' : 'bg-white/10 text-white'}`}>
                        {diffData.common_role_diff_total > 0 ? '+' : ''}{diffData.common_role_diff_total} pts
                      </span>
                    </div>
                    <div className="space-y-2">
                      {diffData.common_role_diff.map((row, i) => (
                        <div key={i} className="flex gap-2">
                          {renderPlayerEntry(row.left, 'left')}
                          {renderPlayerEntry(row.right, 'right')}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Common players same assignment */}
                {diffData.common_players.length > 0 && (
                  <div className="bg-white/5 border border-white/10 rounded-2xl p-4">
                    <h3 className="text-white font-semibold text-sm mb-3">Common Players (Same Role)</h3>
                    <div className="space-y-2">
                      {diffData.common_players.map((row, i) => (
                        <div key={i} className="flex gap-2">
                          {renderPlayerEntry(row.left, 'left')}
                          {renderPlayerEntry(row.right, 'right')}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}

            {diffData?.error && !diffLoading && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-2xl p-4 text-red-400 text-sm">
                {diffData.error}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
