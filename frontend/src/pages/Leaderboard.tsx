import { Link } from 'react-router-dom';
import { useState, useEffect, useRef } from 'react';
import client from '../api/client';
import { useAuth } from '../auth/AuthContext';
import type { LeaderboardEntry } from '../types';

type SortMode = 'points' | 'medals';

function medalScore(e: LeaderboardEntry) {
  return e.gold * 10000 + e.silver * 100 + e.bronze;
}

export default function LeaderboardPage() {
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [sortMode, setSortMode] = useState<SortMode>('points');
  const { profile } = useAuth();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchLeaderboard = async () => {
    try {
      const res = await client.get('/api/leaderboard');
      setEntries(res.data || []);
    } catch { /* silent */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    fetchLeaderboard();
    intervalRef.current = setInterval(fetchLeaderboard, 1800000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchLeaderboard();
    setRefreshing(false);
  };

  const sorted = [...entries].sort((a, b) => {
    if (sortMode === 'medals') {
      const ms = medalScore(b) - medalScore(a);
      if (ms !== 0) return ms;
      return b.points - a.points;
    }
    return b.points - a.points;
  });

  const ranked: (LeaderboardEntry & { rank: number })[] = [];
  sorted.forEach((entry, i) => {
    const key = sortMode === 'medals' ? medalScore(entry) : entry.points;
    const prevKey = i > 0 ? (sortMode === 'medals' ? medalScore(sorted[i - 1]) : sorted[i - 1].points) : null;
    let rank = i + 1;
    if (i > 0 && key === prevKey) {
      rank = ranked[i - 1].rank;
    }
    ranked.push({ ...entry, rank });
  });

  const top3 = ranked.slice(0, 3);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold text-white">Leaderboard</h2>
        <div className="flex items-center gap-2">
          <Link to="/dashboard" className="p-2 hover:bg-white/10 rounded-xl transition-all" title="Back">
            <svg className="w-5 h-5 text-white/60" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </Link>
          <button onClick={handleRefresh} disabled={refreshing}
            className="p-2 hover:bg-white/10 rounded-xl transition-all disabled:opacity-50" title="Refresh">
            <svg className={`w-5 h-5 text-white/50 ${refreshing ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white" />
        </div>
      ) : ranked.length === 0 ? (
        <div className="text-center py-16 text-white/40">No leaderboard data yet.</div>
      ) : (
        <>
          {/* Sort Toggle */}
          <div className="flex items-center justify-center gap-1 mb-6">
            <div className="bg-white/5 border border-white/10 rounded-xl p-1 flex">
              <button
                onClick={() => setSortMode('points')}
                className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-all ${sortMode === 'points' ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' : 'text-white/40 hover:text-white/60'}`}
              >
                Points
              </button>
              <button
                onClick={() => setSortMode('medals')}
                className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-all ${sortMode === 'medals' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' : 'text-white/40 hover:text-white/60'}`}
              >
                Medals
              </button>
            </div>
          </div>

          {/* Podium */}
          {top3.length >= 3 && (
            <div className="flex items-end justify-center gap-3 sm:gap-5 mb-8 pt-4">
              {/* 2nd Place */}
              <div className="flex flex-col items-center">
                <div className="w-16 h-16 sm:w-20 sm:h-20 bg-slate-500/10 border-2 border-slate-400/20 rounded-2xl flex items-center justify-center mb-2">
                  <span className="text-2xl sm:text-3xl">&#x1F948;</span>
                </div>
                <p className="text-white text-sm font-medium text-center truncate max-w-[5rem]">{top3[1].name}</p>
                <p className="text-blue-400 text-xs font-bold">{top3[1].points} pts</p>
                <div className="flex items-center gap-1 mt-1">
                  {top3[1].gold > 0 && <span className="text-[10px]">&#x1F947;{top3[1].gold}</span>}
                  {top3[1].silver > 0 && <span className="text-[10px]">&#x1F948;{top3[1].silver}</span>}
                  {top3[1].bronze > 0 && <span className="text-[10px]">&#x1F949;{top3[1].bronze}</span>}
                </div>
              </div>
              {/* 1st Place */}
              <div className="flex flex-col items-center -mt-4">
                <div className="w-20 h-20 sm:w-24 sm:h-24 bg-amber-500/15 border-2 border-amber-400/30 rounded-2xl flex items-center justify-center mb-2 shadow-lg shadow-amber-500/10">
                  <span className="text-3xl sm:text-4xl">&#x1F947;</span>
                </div>
                <p className="text-white text-sm font-bold text-center truncate max-w-[5rem]">{top3[0].name}</p>
                <p className="text-blue-400 text-xs font-bold">{top3[0].points} pts</p>
                <div className="flex items-center gap-1 mt-1">
                  {top3[0].gold > 0 && <span className="text-[10px]">&#x1F947;{top3[0].gold}</span>}
                  {top3[0].silver > 0 && <span className="text-[10px]">&#x1F948;{top3[0].silver}</span>}
                  {top3[0].bronze > 0 && <span className="text-[10px]">&#x1F949;{top3[0].bronze}</span>}
                </div>
              </div>
              {/* 3rd Place */}
              <div className="flex flex-col items-center mt-2">
                <div className="w-16 h-16 sm:w-20 sm:h-20 bg-orange-500/10 border-2 border-orange-500/20 rounded-2xl flex items-center justify-center mb-2">
                  <span className="text-2xl sm:text-3xl">&#x1F949;</span>
                </div>
                <p className="text-white text-sm font-medium text-center truncate max-w-[5rem]">{top3[2].name}</p>
                <p className="text-blue-400 text-xs font-bold">{top3[2].points} pts</p>
                <div className="flex items-center gap-1 mt-1">
                  {top3[2].gold > 0 && <span className="text-[10px]">&#x1F947;{top3[2].gold}</span>}
                  {top3[2].silver > 0 && <span className="text-[10px]">&#x1F948;{top3[2].silver}</span>}
                  {top3[2].bronze > 0 && <span className="text-[10px]">&#x1F949;{top3[2].bronze}</span>}
                </div>
              </div>
            </div>
          )}

          {/* Entry fee info */}
          <div className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 flex items-center justify-between text-xs text-white/40 mb-4">
            <span>Entry: ₹50/match</span>
            <span>Prize: 1st 50% · 2nd 30% · 3rd 20%</span>
          </div>

          {/* Table */}
          <div className="bg-white/5 border border-white/10 rounded-2xl overflow-hidden backdrop-blur-sm">
            {/* Header */}
            <div className="flex items-center px-3 py-2.5 border-b border-white/5 text-xs text-white/30 uppercase tracking-wider">
              <div className="w-8 text-center">#</div>
              <div className="flex-1 ml-2">Player</div>
              <div className="w-16 text-right">Pts</div>
              <div className="w-[4.5rem] text-center">Medals</div>
              <div className="w-20 text-right">Balance</div>
            </div>
            <div className="divide-y divide-white/5">
              {ranked.map((entry, i) => {
                const isMe = profile?.name === entry.name;
                const bal = entry.balance || 0;
                const totalMedals = (entry.gold || 0) + (entry.silver || 0) + (entry.bronze || 0);
                return (
                  <div key={i}
                    className={`flex items-center px-3 py-3 transition-colors ${isMe ? 'bg-white/10' : 'hover:bg-white/5'}`}>
                    <div className="w-8 text-center flex-shrink-0">
                      {entry.rank === 1 ? <span className="text-lg">&#x1F947;</span>
                        : entry.rank === 2 ? <span className="text-lg">&#x1F948;</span>
                        : entry.rank === 3 ? <span className="text-lg">&#x1F949;</span>
                        : <span className="text-white/50 font-semibold text-sm">{entry.rank}</span>}
                    </div>
                    <div className="flex-1 min-w-0 ml-2">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium truncate text-white">{entry.name}</span>
                        {isMe && <span className="flex-shrink-0 px-1.5 py-0.5 text-[10px] font-bold bg-white/20 text-white rounded-md border border-white/20">YOU</span>}
                      </div>
                    </div>
                    <div className="w-16 text-right">
                      <span className="text-blue-400 text-sm font-semibold">{entry.points}</span>
                    </div>
                    <div className="w-[4.5rem] flex items-center justify-center gap-0.5">
                      {totalMedals === 0 ? (
                        <span className="text-white/20 text-xs">-</span>
                      ) : (
                        <>
                          {entry.gold > 0 && <span className="text-[11px]" title="Gold">&#x1F947;{entry.gold}</span>}
                          {entry.silver > 0 && <span className="text-[11px]" title="Silver">&#x1F948;{entry.silver}</span>}
                          {entry.bronze > 0 && <span className="text-[11px]" title="Bronze">&#x1F949;{entry.bronze}</span>}
                        </>
                      )}
                    </div>
                    <div className="w-20 text-right">
                      <span className={`font-bold text-sm ${bal > 0 ? 'text-green-400' : bal < 0 ? 'text-red-400' : 'text-white/40'}`}>
                        {bal > 0 ? '+' : ''}₹{bal}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
