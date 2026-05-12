import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import client from '../api/client';
import { useAuth } from '../auth/AuthContext';
import type { Match } from '../types';
import { getTeamTheme } from '../utils/teamTheme';
import { DashboardSkeleton } from '../components/Skeleton';
import { useAppClock } from '../hooks/useAppClock';

type MatchTab = 'today' | 'upcoming' | 'completed';
type LiveTeamLineupInfo = {
  announced: boolean;
  complete: boolean;
  unannouncedSelected: number;
  substituteSelected: number;
  lineupWindowOpen?: boolean;
};
type MatchContestant = { user_id: number; name: string; last_team_updated: string | null };

export default function DashboardPage() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [myTeams, setMyTeams] = useState<Set<number>>(new Set());
  const [teamLineupInfo, setTeamLineupInfo] = useState<Record<number, LiveTeamLineupInfo>>({});
  const [backupCounts, setBackupCounts] = useState<Record<number, number>>({});
  const [showContestantsForMatch, setShowContestantsForMatch] = useState<Match | null>(null);
  const [matchContestants, setMatchContestants] = useState<MatchContestant[]>([]);
  const [contestantsLoading, setContestantsLoading] = useState(false);
  const [pendingUsers, setPendingUsers] = useState<any[]>([]);
  const [pendingLoading, setPendingLoading] = useState(false);
  const [modalTab, setModalTab] = useState<'playing' | 'missing'>('playing');
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<MatchTab>('today');
  const { profile, loading: authLoading } = useAuth();
  const { todayIST, nowMs } = useAppClock();
  const prefetchedMatchIdsRef = useRef<Set<number>>(new Set());

  const loadDashboard = useCallback(async () => {
    if (!profile) {
      setTeamLineupInfo({});
      setBackupCounts({});
      setLoading(false);
      return;
    }

    try {
      const dashboardStart = performance.now();
      console.time('dashboard:/api/dashboard/matches + /api/teams/my-matches');
      const [matchRes, teamsRes] = await Promise.all([
        client.get('/api/dashboard/matches'),
        client.get('/api/teams/my-matches'),
      ]);
      console.timeEnd('dashboard:/api/dashboard/matches + /api/teams/my-matches');

      const loadedMatches: Match[] = matchRes.data;
      const loadedMyTeams = new Set<number>(teamsRes.data);
      setMatches(loadedMatches);
      setMyTeams(loadedMyTeams);
      setLoading(false);

      const futureMatchesWithTeams = loadedMatches.filter((match) =>
        ['future', 'lineups'].includes(match.status) && loadedMyTeams.has(match.id)
      );

      if (futureMatchesWithTeams.length > 0) {
        const ids = futureMatchesWithTeams.map((match) => match.id).join(',');
        console.time('dashboard:/api/teams/my-lineup-statuses');
        console.time('dashboard:/api/teams/my-backup-counts');
        const [lineupRes, backupRes] = await Promise.all([
          client.get(`/api/teams/my-lineup-statuses?match_ids=${ids}`),
          client.get(`/api/teams/my-backup-counts?match_ids=${ids}`),
        ]);
        console.timeEnd('dashboard:/api/teams/my-lineup-statuses');
        console.timeEnd('dashboard:/api/teams/my-backup-counts');
        setTeamLineupInfo(lineupRes.data || {});

        const counts: Record<number, number> = {};
        Object.entries(backupRes.data || {}).forEach(([matchId, count]) => {
          counts[Number(matchId)] = Number(count || 0);
        });
        setBackupCounts(counts);
      } else {
        setTeamLineupInfo({});
        setBackupCounts({});
      }

      console.log(`dashboard:total ${(performance.now() - dashboardStart).toFixed(1)}ms`);
    } catch {
      setTeamLineupInfo({});
      setBackupCounts({});
      setLoading(false);
    } finally {
      setLoading(false);
    }
  }, [profile]);

  useEffect(() => {
    if (authLoading) {
      return;
    }

    if (!profile) {
      setMatches([]);
      setMyTeams(new Set());
      setTeamLineupInfo({});
      setBackupCounts({});
      setLoading(false);
      return;
    }

    let alive = true;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const run = async () => {
      if (!alive) return;
      await loadDashboard();
      if (!alive) return;
      intervalId = setInterval(() => {
        void loadDashboard();
      }, 30000);
    };

    void run();

    return () => {
      alive = false;
      if (intervalId) clearInterval(intervalId);
    };
  }, [authLoading, loadDashboard, profile]);

  const getCountdown = useCallback((match: Match) => {
    if (match.status !== 'future') return null;
    const matchTime = new Date(`${match.match_date}T${match.match_time}`).getTime();
    const diff = matchTime - nowMs;
    if (diff <= 0) return null;

    const days = Math.floor(diff / 86400000);
    const hours = Math.floor((diff % 86400000) / 3600000);
    const mins = Math.floor((diff % 3600000) / 60000);

    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${mins}m`;
    return `${mins}m`;
  }, [nowMs]);

  const formatDate = (dateStr: string, timeStr: string) => {
    try {
      const dt = new Date(`${dateStr}T${timeStr}`);
      return dt.toLocaleDateString('en-IN', {
        day: 'numeric', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      });
    } catch { return `${dateStr} ${timeStr}`; }
  };

  const formatDateTime = (value: string | null) => {
    if (!value) return 'Unknown';
    try {
      const dt = new Date(value.replace(' ', 'T'));
      return dt.toLocaleString('en-IN', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return value;
    }
  };

  const openContestantsModal = async (match: Match) => {
    setShowContestantsForMatch(match);
    setContestantsLoading(true);
    setMatchContestants([]);
    try {
      const res = await client.get(`/api/teams/contestants?match_id=${match.id}`);
      setMatchContestants(res.data || []);
    } catch {
      setMatchContestants([]);
    } finally {
      setContestantsLoading(false);
    }
  };

  const fetchPendingUsers = async (matchId: number) => {
    setPendingLoading(true);
    setPendingUsers([]);
    try {
      const res = await client.get(`/api/admin/pending-users?match_id=${matchId}`);
      const data = res.data || {};
      setPendingUsers(data.non_participants || []);
    } catch (err) {
      setPendingUsers([]);
    } finally {
      setPendingLoading(false);
    }
  };

  useEffect(() => {
    if (authLoading || !profile || matches.length === 0) {
      return;
    }

    const todayMatchesToPrefetch = matches.filter((match) =>
      (match.match_date === todayIST || match.status === 'live') &&
      ['future', 'lineups'].includes(match.status)
    );

    const pendingMatchIds = todayMatchesToPrefetch
      .map((match) => match.id)
      .filter((matchId) => !prefetchedMatchIdsRef.current.has(matchId));

    if (pendingMatchIds.length === 0) {
      return;
    }

    pendingMatchIds.forEach((matchId) => prefetchedMatchIdsRef.current.add(matchId));

    const timeoutId = setTimeout(() => {
      void Promise.allSettled(
        pendingMatchIds.map((matchId) =>
          client.get(`/api/players?match_id=${matchId}`).catch(() => null)
        )
      );
    }, 1500);

    return () => clearTimeout(timeoutId);
  }, [authLoading, matches, profile, todayIST]);

  // Split matches into tabs
  // Today = today's matches + any live match (even if started yesterday)
  const todayMatches = matches.filter(m => (m.match_date === todayIST || m.status === 'live') && !['completed', 'nr'].includes(m.status));
  const upcomingMatches = matches.filter(m => m.status === 'future' && m.match_date !== todayIST);
  const completedMatches = matches.filter(m => m.status === 'completed' || m.status === 'nr');

  // Auto-select tab: if today has matches show today, else upcoming
  useEffect(() => {
    if (!loading) {
      if (todayMatches.length > 0) setTab('today');
      else if (upcomingMatches.length > 0) setTab('upcoming');
      else setTab('completed');
    }
  }, [loading]);

  const currentMatches = tab === 'today' ? todayMatches : tab === 'upcoming' ? upcomingMatches : completedMatches;
  const displayName = profile?.name || 'Player';
  const isTodayMatch = (match: Match) => match.match_date === todayIST || match.status === 'live';

  const statusBadge = (status: Match['status']) => {
    switch (status) {
      case 'live':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-blue-500/15 text-blue-400 text-xs font-semibold rounded-full border border-blue-500/20">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500" />
            </span>
            LIVE
          </span>
        );
      case 'completed':
        return <span className="px-2.5 py-1 bg-slate-500/15 text-slate-400 text-xs font-semibold rounded-full border border-slate-500/20">COMPLETED</span>;
      case 'nr':
        return <span className="px-2.5 py-1 bg-slate-500/15 text-slate-400 text-xs font-semibold rounded-full border border-slate-500/20">NO RESULT</span>;
      default:
        return <span className="px-2.5 py-1 bg-white/10 text-white/60 text-xs font-semibold rounded-full border border-white/10">UPCOMING</span>;
    }
  };

  const matchAction = (match: Match) => {
    switch (match.status) {
      case 'future':
      case 'lineups': {
        const hasTeam = myTeams.has(match.id);
        return (
          <div className="flex flex-wrap justify-center gap-2">
            <Link to={`/select-team/${match.id}`}
              className={`inline-flex min-w-[8.5rem] items-center justify-center gap-2 px-5 py-2.5 text-sm font-semibold rounded-xl transition-all ${
                hasTeam ? 'bg-amber-500 hover:bg-amber-400 text-black shadow-lg shadow-amber-500/20' : 'bg-blue-500 hover:bg-blue-400 text-white shadow-lg shadow-blue-500/20'
              }`}>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                {hasTeam
                  ? <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  : <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />}
              </svg>
              {hasTeam ? 'Edit Team' : 'Pick a Team'}
            </Link>
            <button
              type="button"
              onClick={() => openContestantsModal(match)}
              className="inline-flex min-w-[8.5rem] items-center justify-center gap-2 px-4 py-2.5 bg-white/10 hover:bg-white/15 text-white text-sm font-medium rounded-xl border border-white/10 transition-all"
            >
              Who&apos;s Playing
            </button>
          </div>
        );
      }
      case 'live':
        return (
          <div className="flex gap-2">
            <Link to={`/view-scores/${match.id}`}
              className="inline-flex items-center gap-2 px-4 py-2.5 bg-blue-500 hover:bg-blue-400 text-white text-sm font-semibold rounded-xl shadow-lg shadow-blue-500/20 transition-all">
              Live Scores
            </Link>
            {myTeams.has(match.id) && (
              <Link to={`/view-scores/${match.id}?tab=myteam`}
                className="inline-flex items-center gap-1 px-3 py-2.5 bg-white/10 hover:bg-white/15 text-white/70 text-xs font-medium rounded-xl border border-white/10 transition-all">
                Team Analysis
              </Link>
            )}
          </div>
        );
      case 'completed':
        return (
          <div className="flex gap-2">
            <Link to={`/view-scores/${match.id}`}
              className="inline-flex items-center gap-2 px-4 py-2 bg-slate-600 hover:bg-slate-500 text-white text-sm font-medium rounded-xl transition-all">
              View Scores
            </Link>
            {myTeams.has(match.id) && (
              <Link to={`/view-scores/${match.id}?tab=myteam`}
                className="inline-flex items-center gap-1 px-3 py-2 bg-white/10 hover:bg-white/15 text-white/70 text-xs font-medium rounded-xl border border-white/10 transition-all">
                Team Analysis
              </Link>
            )}
          </div>
        );
      case 'nr':
        return (
          <div className="flex gap-2">
            <Link to={`/view-scores/${match.id}`}
              className="inline-flex items-center gap-2 px-4 py-2 bg-slate-600 hover:bg-slate-500 text-white text-sm font-medium rounded-xl transition-all">
              No Result
            </Link>
          </div>
        );
    }
  };

  const getPlayingXiCardMessage = (matchId: number) => {
    const info = teamLineupInfo[matchId];
    if (!info || !info.lineupWindowOpen) return null;

    if (!info.announced) {
      return {
        text: 'Playing XI not announced',
        tone: 'text-white/55',
        subtext: 'Waiting for XI update',
      };
    }

    if (!info.complete) {
      return {
        text: 'Playing XI announced, subs not announced',
        tone: 'text-amber-300',
        subtext: 'Substitute list is still incomplete',
      };
    }

    return {
      text: 'Playing XI announced',
      tone: 'text-blue-300',
      subtext: 'Substitutes are also available',
    };
  };

  const tabs: { key: MatchTab; label: string; count: number }[] = [
    { key: 'today', label: "Today", count: todayMatches.length },
    { key: 'upcoming', label: 'Upcoming', count: upcomingMatches.length },
    { key: 'completed', label: 'Completed', count: completedMatches.length },
  ];

  return (
    <div className="-mx-4 -mt-6">
      {/* Hero with Sachin background */}
      <div className="relative overflow-hidden rounded-b-3xl mb-6">
        <div className="absolute inset-0">
          <img src="/sachin.png" alt="" className="w-full h-full object-cover opacity-40" />
          <div className="absolute inset-0 bg-gradient-to-b from-black/40 via-black/60 to-black" />
        </div>
        <div className="relative z-10 px-4 pt-10 pb-8">
          <h2 className="text-2xl sm:text-3xl font-extrabold text-white">
            Welcome, <span className="inline-block max-w-[14rem] truncate align-bottom text-blue-400 sm:max-w-[20rem]">{displayName}</span>
          </h2>
          <p className="text-white/40 text-sm mt-1">Hippies Mahasangram</p>

          {/* Quick Actions */}
          <div className="grid grid-cols-4 gap-2 sm:gap-3 mt-6">
          <Link to="/leaderboard"
            className="flex flex-col items-center gap-2 p-3 bg-amber-500/10 hover:bg-amber-500/15 border border-amber-500/20 rounded-2xl transition-all group">
            <div className="w-9 h-9 bg-amber-500/20 rounded-xl flex items-center justify-center group-hover:scale-110 transition-transform">
              <svg className="w-4 h-4 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
              </svg>
            </div>
            <span className="w-full text-center text-amber-300 text-xs font-medium leading-tight">Leaderboard</span>
          </Link>
          <Link to="/points-table"
            className="flex flex-col items-center gap-2 p-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-2xl transition-all group">
            <div className="w-9 h-9 bg-white/10 rounded-xl flex items-center justify-center group-hover:scale-110 transition-transform">
              <svg className="w-4 h-4 text-white/70" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </div>
            <span className="w-full text-center text-white/50 text-xs font-medium leading-tight">Points Table</span>
          </Link>
          <Link to="/rules"
            className="flex flex-col items-center gap-2 p-3 bg-blue-500/10 hover:bg-blue-500/15 border border-blue-500/20 rounded-2xl transition-all group">
            <div className="w-9 h-9 bg-blue-500/20 rounded-xl flex items-center justify-center group-hover:scale-110 transition-transform">
              <svg className="w-4 h-4 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <span className="w-full text-center text-blue-300 text-xs font-medium leading-tight">Rules</span>
          </Link>
          <Link to="/weekend"
            className="flex flex-col items-center gap-2 p-3 bg-purple-500/10 hover:bg-purple-500/15 border border-purple-500/20 rounded-2xl transition-all group">
            <div className="w-9 h-9 bg-purple-500/20 rounded-xl flex items-center justify-center group-hover:scale-110 transition-transform">
              <svg className="w-4 h-4 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <span className="w-full text-center text-purple-300 text-xs font-medium leading-tight">Weekend Battle</span>
          </Link>
          </div>
        </div>
      </div>

      <div className="px-4 space-y-6">
        {/* Tabs */}
        <div className="flex items-center gap-1 bg-white/5 rounded-xl p-1 border border-white/10">
          {tabs.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
                tab === t.key
                  ? 'bg-white text-black shadow-lg'
                  : 'text-white/50 hover:text-white hover:bg-white/5'
              }`}>
              {t.label}
              <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                tab === t.key ? 'bg-white/20' : 'bg-white/10'
              }`}>{t.count}</span>
            </button>
          ))}
        </div>

        {/* Match Cards */}
        {loading ? (
          <DashboardSkeleton />
        ) : currentMatches.length === 0 ? (
          <div className="text-center py-12 text-white/40 text-sm">
            {tab === 'today' ? "No matches today." : tab === 'upcoming' ? 'No upcoming matches.' : 'No completed matches yet.'}
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {currentMatches.map((match) => (
              <div key={match.id}
                className={`bg-gradient-to-br ${getTeamTheme(match.team1).tintClass} bg-white/5 hover:bg-white/[0.08] border border-white/10 rounded-2xl p-5 transition-all duration-200 md:backdrop-blur-sm`}>
                <div className="flex items-center justify-between mb-3">
                  {statusBadge(match.status)}
                  {match.locked && match.status === 'live' && (
                    <span className="text-xs text-amber-400 flex items-center gap-1">
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                      </svg>
                      Locked
                    </span>
                  )}
                </div>
                <p className="text-white/25 text-[11px] text-center mb-2">
                  Match #{match.id}
                </p>
                <div className="flex items-center justify-center gap-3 mb-2">
                  <span className={`inline-flex items-center gap-1.5 font-bold text-lg text-white`}>
                    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold ${getTeamTheme(match.team1).badgeClass}`}>
                      {getTeamTheme(match.team1).label}
                    </span>
                    {match.team1}
                  </span>
                  <span className="text-white/40 text-sm font-medium px-2 py-0.5 bg-white/5 rounded-lg">vs</span>
                  <span className={`inline-flex items-center gap-1.5 font-bold text-lg text-white`}>
                    {match.team2}
                    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold ${getTeamTheme(match.team2).badgeClass}`}>
                      {getTeamTheme(match.team2).label}
                    </span>
                  </span>
                </div>
                <p className="text-white/40 text-xs text-center mb-1">
                  {formatDate(match.match_date, match.match_time)}
                </p>
                {(match.toss?.announced || match.toss_time) && (match.status === 'future' || match.status === 'lineups') && (
                  <p className="mb-2 text-center">
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-cyan-400/20 bg-cyan-500/10 px-2.5 py-1 text-[11px] font-semibold text-cyan-300">
                      {match.toss?.text ? match.toss.text : `Toss at ${match.toss_time || 'Unknown'}`}
                    </span>
                  </p>
                )}
                {match.venue && (
                  <div className="mb-2 mx-auto max-w-[280px]">
                    <p className="text-white/50 text-[11px] text-center font-medium mb-1">
                      {match.venue.venue}, {match.venue.city}
                    </p>
                    <div className="flex items-center justify-center gap-2 text-[10px]">
                      <span className={`px-2 py-0.5 rounded-full border ${
                        match.venue.pitch_type === 'Batting-friendly'
                          ? 'bg-amber-500/10 border-amber-500/20 text-amber-300'
                          : match.venue.pitch_type === 'Bowling-friendly'
                          ? 'bg-sky-500/10 border-sky-500/20 text-sky-300'
                          : 'bg-white/5 border-white/10 text-white/50'
                      }`}>
                        {match.venue.pitch_type}
                      </span>
                      <span className="text-white/30">Avg {match.venue.avg_first_innings}</span>
                      <span className="text-white/30">Chase {match.venue.chase_win_pct}%</span>
                    </div>
                  </div>
                )}
                {tab === 'today' && match.status === 'future' && getCountdown(match) && (
                  <p className="text-center mb-2">
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-[11px] font-semibold">
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      Starts in {getCountdown(match)}
                    </span>
                  </p>
                )}
                {tab === 'today' && isTodayMatch(match) && ['future', 'lineups'].includes(match.status) && myTeams.has(match.id) && teamLineupInfo[match.id]?.lineupWindowOpen && (() => {
                  const lineupMessage = getPlayingXiCardMessage(match.id);
                  if (!lineupMessage) return null;

                  return (
                    <div className="mb-3 space-y-1 text-center text-xs font-medium">
                      <p className={lineupMessage.tone}>{lineupMessage.text}</p>
                      <p className="text-white/35">{lineupMessage.subtext}</p>
                      {teamLineupInfo[match.id].unannouncedSelected > 0 && (
                        <p className="text-red-300">
                          {teamLineupInfo[match.id].unannouncedSelected} unavailable players in your team
                        </p>
                      )}
                      {teamLineupInfo[match.id].substituteSelected > 0 && (
                        <p className="text-sky-300">
                          {teamLineupInfo[match.id].substituteSelected} substitutes selected
                        </p>
                      )}
                    </div>
                  );
                })()}
                {match.status === 'future' && (backupCounts[match.id] || 0) > 0 && (
                  <div className="mb-3 text-center">
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-sky-400/20 bg-sky-500/10 px-2.5 py-1 text-[11px] font-semibold text-sky-300">
                      Backups: {backupCounts[match.id]}/3
                    </span>
                  </div>
                )}
                {(match.status === 'live' || match.status === 'completed') && match.current_rank != null && (
                  <div className="mb-3 text-center">
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-400/20 bg-amber-500/10 px-2.5 py-1 text-[11px] font-semibold text-amber-300">
                       {match.status === 'completed' ? 'Final Rank' : 'Current Rank'} #{match.current_rank}
                      </span>
                  </div>
                )}
                <div className="flex justify-center">{matchAction(match)}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="text-center text-white/10 text-xs py-6">
        Built by Fantasy Cricket Team
      </div>

      {showContestantsForMatch && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 md:bg-black/70 md:backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#0f0f0f] p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-white/35">Who&apos;s playing</p>
                <h3 className="mt-1 text-lg font-semibold text-white">
                  Match #{showContestantsForMatch.id}: {showContestantsForMatch.team1} vs {showContestantsForMatch.team2}
                </h3>
                
              </div>
              <div className="flex items-center gap-4">
                <div className="inline-flex rounded-lg bg-white/5 p-1">
                  <button
                    className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${modalTab === 'playing' ? 'bg-white text-black' : 'text-white/70'}`}
                    onClick={() => setModalTab('playing')}
                  >
                    Who's Playing {contestantsLoading ? '(...)' : `(${matchContestants.length})`}
                  </button>
                  <button
                    className={`ml-1 px-3 py-1.5 rounded-lg text-sm font-medium transition ${modalTab === 'missing' ? 'bg-white text-black' : 'text-white/70'}`}
                    onClick={async () => {
                      setModalTab('missing');
                      if (showContestantsForMatch && pendingUsers.length === 0) {
                        await fetchPendingUsers(showContestantsForMatch.id);
                      }
                    }}
                  >
                    Who's Missing {pendingLoading ? '(...)' : `(${pendingUsers.length})`}
                  </button>
                </div>
                <button
                  type="button"
                  onClick={() => setShowContestantsForMatch(null)}
                  className="rounded-lg p-2 text-white/50 transition hover:bg-white/10 hover:text-white"
                >
                  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>

            <div className="mt-3 max-h-[60vh] overflow-auto rounded-xl border border-white/10 bg-white/5">
              {modalTab === 'playing' ? (
                contestantsLoading ? (
                  <div className="flex justify-center py-10">
                    <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-white" />
                  </div>
                ) : matchContestants.length === 0 ? (
                  <div className="px-4 py-8 text-center text-sm text-white/40">No contestants have joined this match yet.</div>
                ) : (
                  <div className="divide-y divide-white/5">
                    {matchContestants.map((contestant, index) => (
                      <div key={`${contestant.user_id}-${index}`} className="flex items-center justify-between gap-4 px-4 py-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-white">{contestant.name}</p>
                        </div>
                        <div className="text-right">
                          <p className="text-[11px] uppercase tracking-wide text-white/30">Last updated</p>
                          <p className="text-xs text-white/65">{formatDateTime(contestant.last_team_updated)}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )
              ) : modalTab === 'missing' ? (
                pendingLoading ? (
                  <div className="flex justify-center py-6">
                    <div className="h-6 w-6 animate-spin rounded-full border-b-2 border-white/40" />
                  </div>
                ) : pendingUsers.length === 0 ? (
                  <div className="px-4 py-6 text-center text-sm text-white/40">No pending users for this match.</div>
                ) : (
                  <div className="divide-y divide-white/5">
                    {pendingUsers.map((u: any, idx: number) => (
                      <div key={`${u.id}-${idx}`} className="flex items-center justify-between gap-4 px-4 py-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-white">{u.name}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )
              ) : null}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
