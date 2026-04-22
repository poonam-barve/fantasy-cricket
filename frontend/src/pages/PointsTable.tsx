import { Link } from 'react-router-dom';
import { useState, useEffect, useMemo } from 'react';
import client from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { getTeamTheme } from '../utils/teamTheme';
import type { PointsTableEntry, Match } from '../types';
import RankShiftBadge from '../components/RankShiftBadge';

const PAGE_SIZE = 10;

export default function PointsTablePage() {
  const [data, setData] = useState<(PointsTableEntry & { net?: number })[]>([]);
  const [matchInfo, setMatchInfo] = useState<Record<string, { team1: string; team2: string }>>({});
  const [loading, setLoading] = useState(true);
  const [matchPage, setMatchPage] = useState(0);
  const { profile } = useAuth();

  useEffect(() => {
    Promise.all([
      client.get('/api/points-table'),
      client.get('/api/matches'),
    ])
      .then(([ptRes, matchRes]) => {
        setData(ptRes.data || []);
        const info: Record<string, { team1: string; team2: string }> = {};
        (matchRes.data || []).forEach((m: Match) => {
          info[String(m.id)] = { team1: m.team1, team2: m.team2 };
        });
        setMatchInfo(info);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const contestantSet = new Set<string>();
  const matchMap = new Map<string, Record<string, number>>();
  const netMap = new Map<string, Record<string, number>>();
  const adjustedMap = new Map<string, Record<string, boolean>>();
  const rankChangeMap = new Map<string, number | null>();

  data.forEach((entry) => {
    contestantSet.add(entry.name);
    const mid = String(entry.match_id);
    if (!matchMap.has(mid)) matchMap.set(mid, {});
    if (!netMap.has(mid)) netMap.set(mid, {});
    if (!adjustedMap.has(mid)) adjustedMap.set(mid, {});
    matchMap.get(mid)![entry.name] = entry.points;
    netMap.get(mid)![entry.name] = entry.net || 0;
    adjustedMap.get(mid)![entry.name] = Boolean(entry.adjusted);
    if (entry.rank_change !== undefined) {
      rankChangeMap.set(`${mid}:${entry.name}`, entry.rank_change);
    }
  });

  const contestants = Array.from(contestantSet);
  const matchIds = Array.from(matchMap.keys());

  // Pagination
  const totalPages = Math.max(1, Math.ceil(matchIds.length / PAGE_SIZE));
  const visibleMatchIds = useMemo(
    () => matchIds.slice(matchPage * PAGE_SIZE, (matchPage + 1) * PAGE_SIZE),
    [matchIds.length, matchPage]
  );
  const rangeStart = matchPage * PAGE_SIZE + 1;
  const rangeEnd = Math.min((matchPage + 1) * PAGE_SIZE, matchIds.length);
  const latestMatchId = useMemo(() => {
    if (matchIds.length === 0) return null;
    return [...matchIds].sort((a, b) => Number(b) - Number(a))[0];
  }, [matchIds]);
  const latestRankChangeByContestant = useMemo(() => {
    const latest = new Map<string, number | null>();
    if (!latestMatchId) return latest;
    contestants.forEach((name) => {
      latest.set(name, rankChangeMap.get(`${latestMatchId}:${name}`) ?? null);
    });
    return latest;
  }, [contestants, latestMatchId, rankChangeMap]);

  // Compute per-match ranks
  const matchRanks = new Map<string, Record<string, number>>();
  matchIds.forEach((mid) => {
    const entries = Object.entries(matchMap.get(mid) || {});
    entries.sort((a, b) => b[1] - a[1]);
    const ranks: Record<string, number> = {};
    entries.forEach(([name, pts], i) => {
      if (i > 0 && pts === entries[i - 1][1]) {
        ranks[name] = ranks[entries[i - 1][0]];
      } else {
        ranks[name] = i + 1;
      }
    });
    matchRanks.set(mid, ranks);
  });

  const totalPoints: Record<string, number> = {};
  contestants.forEach((c) => {
    totalPoints[c] = 0;
    matchIds.forEach((m) => {
      totalPoints[c] += matchMap.get(m)?.[c] || 0;
    });
  });

  const sortedContestants = [...contestants].sort((a, b) => totalPoints[b] - totalPoints[a]);
  const currentUserName = profile?.name || '';

  const rankBadge = (rank: number) => {
    if (rank === 1) return <span className="text-sm">🥇</span>;
    if (rank === 2) return <span className="text-sm">🥈</span>;
    if (rank === 3) return <span className="text-sm">🥉</span>;
    return null;
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-white">Points Table</h2>
        <Link to="/dashboard" className="inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-white/70 hover:bg-white/10 hover:text-white transition-all">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Back
        </Link>
      </div>
      <p className="mb-4 text-xs text-white/40">
        <span className="font-semibold text-amber-300">Adj.</span> marks non-participant adjustment points used only for standings.
      </p>

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white" />
        </div>
      ) : data.length === 0 ? (
        <div className="text-center py-16 text-white/30">No points data available yet.</div>
      ) : (
        <>
        {/* Match pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between mb-3">
            <button
              onClick={() => setMatchPage(p => Math.max(0, p - 1))}
              disabled={matchPage === 0}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-white/50 hover:bg-white/10 hover:text-white transition-all disabled:opacity-25 disabled:hover:bg-transparent disabled:hover:text-white/50"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" /></svg>
              Prev
            </button>
            <span className="text-xs text-white/40">
              Matches {rangeStart}-{rangeEnd} of {matchIds.length}
            </span>
            <button
              onClick={() => setMatchPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={matchPage >= totalPages - 1}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-white/50 hover:bg-white/10 hover:text-white transition-all disabled:opacity-25 disabled:hover:bg-transparent disabled:hover:text-white/50"
            >
              Next
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
            </button>
          </div>
        )}

        <div className="bg-white/5 border border-white/10 rounded-2xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-white/5">
                  <th className="sticky left-0 z-20 bg-black px-4 py-3 text-left text-xs font-medium text-white/30 uppercase tracking-wider whitespace-nowrap border-r border-white/5 min-w-[9.5rem]">
                    Player
                  </th>
                  <th className="sticky left-[9.5rem] z-20 bg-black px-2 py-3 text-center text-xs font-medium text-white/30 uppercase tracking-wider whitespace-nowrap border-r border-white/5 min-w-[4.5rem]">
                    Total
                  </th>
                  {visibleMatchIds.map((mid) => {
                    const mi = matchInfo[mid];
                    const t1 = mi ? getTeamTheme(mi.team1).label : '';
                    const t2 = mi ? getTeamTheme(mi.team2).label : '';
                    return (
                      <th key={mid} className="px-2 py-3 text-center text-xs font-medium text-white/30 whitespace-nowrap min-w-[5rem]">
                        {mi ? (
                          <div className="flex flex-col items-center gap-0.5">
                            <span className="text-white/50 font-semibold text-[10px]">{t1} v {t2}</span>
                            <span className="text-white/20 text-[9px]">M{mid}</span>
                          </div>
                        ) : (
                          <span className="uppercase tracking-wider">M{mid}</span>
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {sortedContestants.map((c) => {
                  const isMe = c === currentUserName;
                  return (
                    <tr key={c} className={`transition-colors ${isMe ? 'bg-white/10' : 'hover:bg-white/5'}`}>
                      <td className={`sticky left-0 z-10 px-4 py-3 text-white font-medium whitespace-nowrap border-r border-white/5 min-w-[9.5rem] ${isMe ? 'bg-black' : 'bg-black'}`}>
                        <div className="flex items-center gap-1.5 min-w-0">
                          <RankShiftBadge delta={latestRankChangeByContestant.get(c) ?? undefined} compact className="shrink-0" />
                          <span className="truncate max-w-[8rem] sm:max-w-[10rem]">{c}</span>
                          {isMe && <span className="px-1 py-0.5 text-[8px] font-bold bg-white/20 text-white rounded">YOU</span>}
                        </div>
                      </td>
                      <td className={`sticky left-[9.5rem] z-10 px-2 py-3 text-center font-bold text-white whitespace-nowrap border-r border-white/5 min-w-[4.5rem] ${isMe ? 'bg-black' : 'bg-black'}`}>
                        {totalPoints[c]}
                      </td>
                      {visibleMatchIds.map((mid) => {
                        const pts = matchMap.get(mid)?.[c] || 0;
                        const net = netMap.get(mid)?.[c] || 0;
                        const rank = matchRanks.get(mid)?.[c];
                        const isAdjusted = adjustedMap.get(mid)?.[c] || false;
                        return (
                          <td key={mid} className="px-2 py-2 text-center whitespace-nowrap min-w-[5rem]">
                            {pts ? (
                              <div>
                                <div className="flex items-center justify-center gap-1">
                                  {rankBadge(rank || 99)}
                                  <span className={`font-medium ${isAdjusted ? 'text-amber-300' : 'text-white'}`}>{pts}</span>
                                </div>
                                {isAdjusted ? (
                                  <div className="text-[10px] text-amber-400">Adj.</div>
                                ) : (
                                  <div className={`text-[10px] ${net > 0 ? 'text-green-400' : net < 0 ? 'text-red-400' : 'text-white/20'}`}>
                                    {net > 0 ? '+' : ''}{net}
                                  </div>
                                )}
                              </div>
                            ) : (
                              <span className="text-white/10">-</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Bottom pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-1 mt-3">
            {Array.from({ length: totalPages }, (_, i) => (
              <button
                key={i}
                onClick={() => setMatchPage(i)}
                className={`w-8 h-8 rounded-lg text-xs font-semibold transition-all ${
                  matchPage === i
                    ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                    : 'text-white/40 hover:bg-white/10 hover:text-white/60'
                }`}
              >
                {i + 1}
              </button>
            ))}
          </div>
        )}
        </>
      )}
    </div>
  );
}
