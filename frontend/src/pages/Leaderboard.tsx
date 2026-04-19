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

          {/* F1-Style Podium */}
          {top3.length >= 3 && (
            <div className="mb-8">
              {/* Driver names + info above podium blocks */}
              <div className="flex items-end justify-center gap-0 px-2">
                {/* P2 - Left */}
                <div className="flex flex-col items-center w-[30%] max-w-[7.5rem]">
                  <span className="text-2xl mb-1">&#x1F948;</span>
                  <p className="text-white text-xs sm:text-sm font-semibold text-center truncate w-full">{top3[1].name}</p>
                  <p className="text-blue-400 text-[11px] font-bold">{top3[1].points} pts</p>
                  <div className="flex items-center gap-1 mt-0.5 mb-2">
                    {top3[1].gold > 0 && <span className="text-[10px]">&#x1F947;{top3[1].gold}</span>}
                    {top3[1].silver > 0 && <span className="text-[10px]">&#x1F948;{top3[1].silver}</span>}
                    {top3[1].bronze > 0 && <span className="text-[10px]">&#x1F949;{top3[1].bronze}</span>}
                  </div>
                  {/* P2 Block */}
                  <div className="w-full h-20 sm:h-24 rounded-tl-xl bg-gradient-to-b from-slate-400/30 to-slate-500/10 border border-white/10 border-b-0 flex items-center justify-center">
                    <span className="text-3xl sm:text-4xl font-black text-white/20">2</span>
                  </div>
                </div>
                {/* P1 - Center */}
                <div className="flex flex-col items-center w-[34%] max-w-[8.5rem] -mx-[1px]">
                  <span className="text-3xl mb-1">&#x1F947;</span>
                  <p className="text-white text-xs sm:text-sm font-bold text-center truncate w-full">{top3[0].name}</p>
                  <p className="text-blue-400 text-[11px] font-bold">{top3[0].points} pts</p>
                  <div className="flex items-center gap-1 mt-0.5 mb-2">
                    {top3[0].gold > 0 && <span className="text-[10px]">&#x1F947;{top3[0].gold}</span>}
                    {top3[0].silver > 0 && <span className="text-[10px]">&#x1F948;{top3[0].silver}</span>}
                    {top3[0].bronze > 0 && <span className="text-[10px]">&#x1F949;{top3[0].bronze}</span>}
                  </div>
                  {/* P1 Block - tallest */}
                  <div className="w-full h-28 sm:h-36 rounded-t-xl bg-gradient-to-b from-amber-400/30 to-amber-600/10 border border-amber-400/20 border-b-0 flex items-center justify-center shadow-lg shadow-amber-500/10">
                    <span className="text-4xl sm:text-5xl font-black text-amber-400/25">1</span>
                  </div>
                </div>
                {/* P3 - Right */}
                <div className="flex flex-col items-center w-[30%] max-w-[7.5rem]">
                  <span className="text-2xl mb-1">&#x1F949;</span>
                  <p className="text-white text-xs sm:text-sm font-semibold text-center truncate w-full">{top3[2].name}</p>
                  <p className="text-blue-400 text-[11px] font-bold">{top3[2].points} pts</p>
                  <div className="flex items-center gap-1 mt-0.5 mb-2">
                    {top3[2].gold > 0 && <span className="text-[10px]">&#x1F947;{top3[2].gold}</span>}
                    {top3[2].silver > 0 && <span className="text-[10px]">&#x1F948;{top3[2].silver}</span>}
                    {top3[2].bronze > 0 && <span className="text-[10px]">&#x1F949;{top3[2].bronze}</span>}
                  </div>
                  {/* P3 Block - shortest */}
                  <div className="w-full h-14 sm:h-18 rounded-tr-xl bg-gradient-to-b from-orange-400/25 to-orange-600/10 border border-orange-400/15 border-b-0 flex items-center justify-center">
                    <span className="text-3xl sm:text-4xl font-black text-white/15">3</span>
                  </div>
                </div>
              </div>
              {/* Podium base line */}
              <div className="mx-2 h-[2px] bg-gradient-to-r from-transparent via-white/20 to-transparent" />
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
              <div className="w-14 text-right">Pts</div>
              <div className="w-8 text-center">&#x1F947;</div>
              <div className="w-8 text-center">&#x1F948;</div>
              <div className="w-8 text-center">&#x1F949;</div>
              <div className="w-[4.5rem] text-right">Balance</div>
            </div>
            <div className="divide-y divide-white/5">
              {ranked.map((entry, i) => {
                const isMe = profile?.name === entry.name;
                const bal = entry.balance || 0;
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
                    <div className="w-14 text-right">
                      <span className="text-blue-400 text-sm font-semibold">{entry.points}</span>
                    </div>
                    <div className="w-8 text-center">
                      <span className={`text-xs font-semibold ${entry.gold ? 'text-amber-400' : 'text-white/15'}`}>{entry.gold || '-'}</span>
                    </div>
                    <div className="w-8 text-center">
                      <span className={`text-xs font-semibold ${entry.silver ? 'text-slate-300' : 'text-white/15'}`}>{entry.silver || '-'}</span>
                    </div>
                    <div className="w-8 text-center">
                      <span className={`text-xs font-semibold ${entry.bronze ? 'text-orange-400' : 'text-white/15'}`}>{entry.bronze || '-'}</span>
                    </div>
                    <div className="w-[4.5rem] text-right">
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
