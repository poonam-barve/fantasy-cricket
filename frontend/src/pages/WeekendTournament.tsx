import { Link } from 'react-router-dom';
import { useState, useEffect } from 'react';
import client from '../api/client';
import { useAuth } from '../auth/AuthContext';
import type { WeekendTournament, WeekendTournamentRound, WeekendTournamentMatchup, WeekendTournamentHistory } from '../types';

const ROUND_COLORS: Record<number, string> = {
  1: 'text-blue-400',
  2: 'text-purple-400',
  3: 'text-amber-400',
  4: 'text-green-400',
};

function MatchupCard({ matchup, isMe }: { matchup: WeekendTournamentMatchup; isMe: (id: number) => boolean }) {
  const done = matchup.status === 'completed';
  const live = matchup.status === 'live';

  const renderPlayer = (
    user: { id: number; name: string } | null,
    points: number,
    isWinner: boolean,
    isLoser: boolean,
  ) => {
    if (!user) return <div className="px-2 py-1.5 text-xs text-white/20 italic">TBD</div>;
    const me = isMe(user.id);
    return (
      <div className={`flex items-center justify-between px-2 py-1.5 ${isWinner ? 'bg-green-500/10' : isLoser ? 'bg-red-500/5 opacity-50' : ''}`}>
        <div className="flex items-center gap-1 min-w-0">
          <span className={`text-xs font-medium truncate ${isWinner ? 'text-green-400' : 'text-white'}`}>{user.name}</span>
          {me && <span className="px-1 py-0.5 text-[7px] font-bold bg-white/20 text-white rounded">YOU</span>}
        </div>
        {(done || live) && (
          <span className={`text-[11px] font-bold ml-1 flex-shrink-0 ${isWinner ? 'text-green-400' : 'text-white/40'}`}>{points}</span>
        )}
      </div>
    );
  };

  const u1Winner = done && matchup.winner_user_id === matchup.user1?.id;
  const u2Winner = done && matchup.winner_user_id === matchup.user2?.id;

  return (
    <div className={`rounded-lg border overflow-hidden ${live ? 'border-green-500/40 shadow-sm shadow-green-500/10' : 'border-white/10'} bg-white/5`}>
      {live && <div className="bg-green-500/20 text-center text-[9px] font-bold text-green-400 py-0.5 tracking-wider">LIVE</div>}
      {renderPlayer(matchup.user1, matchup.user1_points, u1Winner, done && !u1Winner)}
      <div className="h-px bg-white/10" />
      {renderPlayer(matchup.user2, matchup.user2_points, u2Winner, done && !u2Winner)}
    </div>
  );
}

function BracketDiagram({ rounds, isMe }: { rounds: WeekendTournamentRound[]; isMe: (id: number) => boolean }) {
  if (rounds.length === 0) return <div className="text-center text-white/30 py-8 text-sm">Bracket not yet drawn</div>;

  return (
    <div className="overflow-x-auto pb-4">
      <div className="flex gap-4 sm:gap-6 min-w-max px-2">
        {rounds.map((round) => {
          const roundMatchups = round.matchups;
          // Calculate spacing to vertically center matchups with connectors
          const gapClass = round.round === 1 ? 'gap-2' : round.round === 2 ? 'gap-6' : round.round === 3 ? 'gap-14' : 'gap-0';

          return (
            <div key={round.round} className="flex flex-col">
              {/* Round header */}
              <div className="text-center mb-3">
                <div className={`text-[10px] font-bold uppercase tracking-wider ${ROUND_COLORS[round.round] || 'text-white/40'}`}>
                  {round.round_label}
                </div>
              </div>
              {/* Matchups */}
              <div className={`flex flex-col ${gapClass} justify-center flex-1`} style={{ width: '140px' }}>
                {roundMatchups.map((matchup) => (
                  <MatchupCard key={matchup.position} matchup={matchup} isMe={isMe} />
                ))}
              </div>
            </div>
          );
        })}

        {/* Winner column */}
        {rounds.length > 0 && (() => {
          const lastRound = rounds[rounds.length - 1];
          const finalMatchup = lastRound.matchups[0];
          if (!finalMatchup || finalMatchup.status !== 'completed' || !finalMatchup.winner_user_id) return null;
          const winnerName = finalMatchup.winner_user_id === finalMatchup.user1?.id
            ? finalMatchup.user1.name
            : finalMatchup.user2?.name;

          return (
            <div className="flex flex-col justify-center items-center" style={{ width: '100px' }}>
              <span className="text-3xl mb-1">&#x1F3C6;</span>
              <span className="text-xs font-bold text-amber-400 text-center">{winnerName}</span>
              <span className="text-[9px] text-amber-400/60 mt-0.5">Weekend Champion</span>
            </div>
          );
        })()}
      </div>
    </div>
  );
}

export default function WeekendTournamentPage() {
  const [tournament, setTournament] = useState<WeekendTournament | null>(null);
  const [history, setHistory] = useState<WeekendTournamentHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const { profile } = useAuth();

  const fetchData = async () => {
    try {
      const [currentRes, historyRes] = await Promise.all([
        client.get('/api/weekend-tournament/current'),
        client.get('/api/weekend-tournament/history'),
      ]);
      setTournament(currentRes.data);
      setHistory(historyRes.data || []);
    } catch { /* silent */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchData(); }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchData();
    setRefreshing(false);
  };

  const isMe = (id: number) => profile?.id === id;

  const statusLabel = (status: string) => {
    switch (status) {
      case 'pending': return { text: 'Upcoming', color: 'bg-blue-500/20 text-blue-400 border-blue-500/30' };
      case 'qualifying': return { text: 'Qualifying', color: 'bg-amber-500/20 text-amber-400 border-amber-500/30' };
      case 'active': return { text: 'Live', color: 'bg-green-500/20 text-green-400 border-green-500/30' };
      case 'completed': return { text: 'Completed', color: 'bg-white/10 text-white/50 border-white/20' };
      default: return { text: 'None', color: 'bg-white/5 text-white/30 border-white/10' };
    }
  };

  const getMatchLabel = (matchId: number) => {
    if (!tournament?.matches) return `M${matchId}`;
    const m = tournament.matches[String(matchId)];
    return m ? `${m.team1} vs ${m.team2}` : `M${matchId}`;
  };

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold text-white">Weekend Battle</h2>
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
      ) : !tournament || tournament.status === 'none' ? (
        <div className="text-center py-16">
          <span className="text-4xl mb-4 block">&#x1F3CF;</span>
          <p className="text-white/40 text-sm">No weekend competition available right now.</p>
          <p className="text-white/25 text-xs mt-1">Competitions run on weekends with 4 matches (2 Sat + 2 Sun).</p>
        </div>
      ) : (
        <>
          {/* Status Banner */}
          <div className="bg-white/5 border border-white/10 rounded-2xl p-4 mb-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold text-white">Weekend Champion</span>
              <span className={`px-2 py-0.5 text-[10px] font-bold rounded-full border ${statusLabel(tournament.status).color}`}>
                {statusLabel(tournament.status).text}
              </span>
            </div>

            {/* Winner display */}
            {tournament.status === 'completed' && tournament.winner && (
              <div className="flex items-center gap-3 bg-amber-500/10 border border-amber-500/20 rounded-xl p-3 mb-3">
                <span className="text-3xl">&#x1F3C6;</span>
                <div>
                  <p className="text-amber-400 text-sm font-bold">{tournament.winner.name}</p>
                  <p className="text-amber-400/60 text-[10px]">Weekend Champion</p>
                </div>
              </div>
            )}

            {/* Match progress */}
            {tournament.weekend_match_ids && (
              <div className="flex items-center gap-1 mt-2">
                {/* Qualifier */}
                <div className="flex-1 text-center">
                  <div className="text-[9px] text-white/30 mb-1">QUALIFIER</div>
                  <div className={`h-1.5 rounded-full ${
                    tournament.matches?.[String(tournament.qualifying_match_id)]?.status === 'completed'
                      ? 'bg-green-500' : 'bg-white/10'
                  }`} />
                  <div className="text-[8px] text-white/20 mt-1 truncate">
                    {tournament.qualifying_match_id ? getMatchLabel(tournament.qualifying_match_id) : ''}
                  </div>
                </div>
                {/* Weekend matches */}
                {['Ro16', 'QF', 'SF', 'Final'].map((label, i) => {
                  const mid = tournament.weekend_match_ids![i];
                  const mStatus = tournament.matches?.[String(mid)]?.status || 'future';
                  return (
                    <div key={i} className="flex-1 text-center">
                      <div className={`text-[9px] mb-1 ${ROUND_COLORS[i + 1] || 'text-white/30'}`}>{label}</div>
                      <div className={`h-1.5 rounded-full ${
                        mStatus === 'completed' ? 'bg-green-500' : mStatus === 'live' ? 'bg-green-500 animate-pulse' : 'bg-white/10'
                      }`} />
                      <div className="text-[8px] text-white/20 mt-1 truncate">{getMatchLabel(mid)}</div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Qualifiers */}
          {tournament.qualifiers && tournament.qualifiers.length > 0 && (
            <div className="bg-white/5 border border-white/10 rounded-2xl p-4 mb-4">
              <h3 className="text-sm font-semibold text-white mb-3">
                Qualified Players
                <span className="text-white/30 font-normal ml-1">({tournament.qualifiers.length})</span>
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                {tournament.qualifiers.map((q, i) => (
                  <div key={q.user_id}
                    className={`flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-xs ${
                      isMe(q.user_id) ? 'bg-white/10' : 'bg-white/[0.02]'
                    }`}>
                    <span className="text-white/30 w-4 text-right text-[10px]">{i + 1}.</span>
                    <span className={`truncate ${isMe(q.user_id) ? 'text-white font-semibold' : 'text-white/70'}`}>
                      {q.name}
                    </span>
                    {q.backfilled && <span className="text-[8px] text-amber-400/60">LB</span>}
                    <span className="text-white/25 text-[10px] ml-auto flex-shrink-0">{q.qualifying_points}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Bracket */}
          {tournament.brackets && tournament.brackets.length > 0 && (
            <div className="bg-white/5 border border-white/10 rounded-2xl p-4 mb-4">
              <h3 className="text-sm font-semibold text-white mb-4">Bracket</h3>
              <BracketDiagram rounds={tournament.brackets} isMe={isMe} />
            </div>
          )}

          {/* History */}
          {history.length > 0 && (
            <div className="bg-white/5 border border-white/10 rounded-2xl p-4">
              <h3 className="text-sm font-semibold text-white mb-3">Past Winners</h3>
              <div className="space-y-1.5">
                {history.filter(h => h.status === 'completed' && h.winner).map((h) => (
                  <div key={h.id} className="flex items-center justify-between px-3 py-2 bg-white/[0.02] rounded-lg">
                    <div className="flex items-center gap-2">
                      <span className="text-sm">&#x1F3C6;</span>
                      <span className="text-xs font-medium text-white">{h.winner!.name}</span>
                    </div>
                    <span className="text-[10px] text-white/30">{h.qualifier_date}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
