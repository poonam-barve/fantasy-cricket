import { Link } from 'react-router-dom';
import { useState, useEffect, useRef } from 'react';
import client from '../api/client';
import { useAuth } from '../auth/AuthContext';
import type { WeekendTournament, WeekendTournamentRound, WeekendTournamentMatchup, WeekendTournamentHistory } from '../types';

const ROUND_COLORS: Record<number, string> = {
  1: 'text-blue-400',
  2: 'text-purple-400',
  3: 'text-amber-400',
  4: 'text-green-400',
};

const ROUND_MATCHUP_COUNTS: Record<number, number> = {
  1: 8,
  2: 4,
  3: 2,
  4: 1,
};

function getBracketSlots(matchupCount: number) {
  if (matchupCount <= 0) return [];
  const totalRows = ROUND_MATCHUP_COUNTS[1] * 2 - 1;
  const step = totalRows / matchupCount;
  return Array.from({ length: matchupCount }, (_, index) => Math.round((index + 0.5) * step - 0.5));
}

function MatchupCard({ matchup, isMe, compact = false }: { matchup: WeekendTournamentMatchup; isMe: (id: number) => boolean; compact?: boolean }) {
  const done = matchup.status === 'completed';
  const live = matchup.status === 'live';
  const u1Winner = done && matchup.winner_user_id === matchup.user1?.id;
  const u2Winner = done && matchup.winner_user_id === matchup.user2?.id;
  const hasResult = done && !!matchup.winner_user_id;

  const renderPlayer = (
    user: { id: number; name: string } | null,
    points: number,
    isWinner: boolean,
    isLoser: boolean,
    positionLabel: string,
  ) => {
    if (!user) {
      return (
        <div className={`flex items-center justify-between rounded-md border border-dashed border-white/10 text-xs text-white/20 italic ${compact ? 'px-1.5 py-1.5' : 'px-2 py-2'}`}>
          <span>TBD</span>
          <span className="text-[9px] uppercase tracking-[0.18em] text-white/10">{positionLabel}</span>
        </div>
      );
    }
    const me = isMe(user.id);
    const blockTone = isWinner
      ? 'border-green-400/25 bg-green-500/15 text-green-50'
      : isLoser
        ? 'border-red-400/20 bg-red-500/12 text-red-50'
        : 'border-white/10 bg-white/[0.03] text-white';
    return (
      <div className={`flex items-center justify-between rounded-md border transition-colors ${compact ? 'px-1.5 py-1.5' : 'px-2 py-2'} ${blockTone}`}>
        <div className="flex items-center gap-1 min-w-0">
          <span className={`font-medium truncate ${compact ? 'text-[10px]' : 'text-xs'} ${isWinner ? 'text-green-200' : isLoser ? 'text-red-100' : 'text-white'}`}>
            {user.name}
          </span>
          {me && <span className="px-1 py-0.5 text-[7px] font-bold bg-white/20 text-white rounded">YOU</span>}
          {isWinner && done && <span className="px-1 py-0.5 text-[7px] font-bold rounded bg-green-500/20 text-green-100">WIN</span>}
          {isLoser && done && <span className="px-1 py-0.5 text-[7px] font-bold rounded bg-red-500/20 text-red-100">OUT</span>}
        </div>
        {(done || live) && (
          <span className={`font-bold ml-1 flex-shrink-0 ${compact ? 'text-[10px]' : 'text-[11px]'} ${isWinner ? 'text-green-100' : isLoser ? 'text-red-100/80' : 'text-white/50'}`}>{points}</span>
        )}
      </div>
    );
  };

  return (
    <div className={`rounded-xl border overflow-hidden ${live ? 'border-green-500/40 shadow-sm shadow-green-500/10' : hasResult ? 'border-white/15' : 'border-white/10'} bg-gradient-to-br from-white/[0.06] to-white/[0.03]`}>
      <div className={compact ? 'space-y-0.5 p-1.5' : 'space-y-1 p-2'}>
        {renderPlayer(matchup.user1, matchup.user1_points, u1Winner, done && !u1Winner, 'A')}
        {renderPlayer(matchup.user2, matchup.user2_points, u2Winner, done && !u2Winner, 'B')}
      </div>
    </div>
  );
}

function ConnectorBridge({
  fromSlots,
  toSlots,
  rowHeight,
  cardHeight,
  topOffset,
  bridgeWidth,
}: {
  fromSlots: number[];
  toSlots: number[];
  rowHeight: number;
  cardHeight: number;
  topOffset: number;
  bridgeWidth: number;
}) {
  if (fromSlots.length === 0 || toSlots.length === 0) return null;

  const totalRows = ROUND_MATCHUP_COUNTS[1] * 2 - 1;
  const height = topOffset + totalRows * rowHeight + cardHeight;
  const sourceX = 0;
  const elbowX = 8;
  const targetX = bridgeWidth;

  const paths = fromSlots.map((slot, index) => {
    const targetSlot = toSlots[Math.floor(index / 2)];
    if (targetSlot === undefined) return null;

    const sourceY = topOffset + slot * rowHeight + cardHeight / 2;
    const targetY = topOffset + targetSlot * rowHeight + cardHeight / 2;

    return `M ${sourceX} ${sourceY} H ${elbowX} V ${targetY} H ${targetX}`;
  }).filter(Boolean) as string[];

  return (
    <div className="relative shrink-0" style={{ width: bridgeWidth, height }}>
      <svg className="absolute inset-0 h-full w-full overflow-visible" viewBox={`0 0 ${bridgeWidth} ${height}`} fill="none" aria-hidden="true">
        {paths.map((d, index) => (
          <path
            key={index}
            d={d}
            stroke="rgba(255,255,255,0.18)"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
      </svg>
    </div>
  );
}

function BracketDiagram({ rounds, isMe }: { rounds: WeekendTournamentRound[]; isMe: (id: number) => boolean }) {
  const [isCompact, setIsCompact] = useState(() => typeof window !== 'undefined' ? window.innerWidth < 640 : false);
  const finalRoundRef = useRef<HTMLDivElement | null>(null);
  const didAutoScrollRef = useRef(false);

  useEffect(() => {
    const update = () => setIsCompact(window.innerWidth < 640);
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  if (rounds.length === 0) return <div className="text-center text-white/30 py-8 text-sm">Bracket not yet drawn</div>;

  const roundsByNumber = new Map(rounds.map((round) => [round.round, round]));
  const visibleRounds = [1, 2, 3, 4];
  const fallbackRoundLabels: Record<number, string> = {
    1: 'Round of 16',
    2: 'Quarter Finals',
    3: 'Semi Finals',
    4: 'Final',
  };
  const rowHeight = isCompact ? 50 : 72;
  const cardHeight = isCompact ? 42 : 64;
  const topOffset = isCompact ? 8 : 28;
  const bridgeWidth = isCompact ? 20 : 16;
  const totalRows = ROUND_MATCHUP_COUNTS[1] * 2 - 1;
  const totalHeight = topOffset + totalRows * rowHeight + cardHeight;
  const finalMatchup = roundsByNumber.get(4)?.matchups?.[0];
  const finalHasTwoUsers = Boolean(finalMatchup?.user1 && finalMatchup?.user2);

  useEffect(() => {
    if (!finalHasTwoUsers || didAutoScrollRef.current) return;
    finalRoundRef.current?.scrollIntoView({ behavior: 'auto', block: 'nearest', inline: 'end' });
    didAutoScrollRef.current = true;
  }, [finalHasTwoUsers]);

  return (
    <div className="overflow-x-auto pb-4">
      <div className="flex items-start min-w-max px-2">
        {visibleRounds.map((roundNumber) => {
          const round = roundsByNumber.get(roundNumber);
          const roundLabel = round?.round_label || fallbackRoundLabels[roundNumber] || `Round ${roundNumber}`;
          const roundMatchups = round?.matchups || [];
          const expectedCount = ROUND_MATCHUP_COUNTS[roundNumber] || 0;
          const renderedMatchups = roundMatchups.length > 0
            ? roundMatchups
            : Array.from({ length: expectedCount }, (_, idx) => ({
                position: idx + 1,
                user1: null,
                user2: null,
                user1_points: 0,
                user2_points: 0,
                winner_user_id: null,
                status: 'pending' as const,
              }));
          const roundSlots = getBracketSlots(renderedMatchups.length);
          const nextRound = roundsByNumber.get(roundNumber + 1);
          const nextRenderedMatchups = nextRound?.matchups?.length
            ? nextRound.matchups
            : Array.from({ length: ROUND_MATCHUP_COUNTS[roundNumber + 1] || 0 }, (_, idx) => ({
                position: idx + 1,
                user1: null,
                user2: null,
                user1_points: 0,
                user2_points: 0,
                winner_user_id: null,
                status: 'pending' as const,
              }));
          const nextSlots = getBracketSlots(nextRenderedMatchups.length);

          return (
            <div
              key={roundNumber}
              ref={roundNumber === 4 ? finalRoundRef : undefined}
              className="flex items-start"
            >
              <div className="relative shrink-0 w-[104px] sm:w-[136px] md:w-[152px] lg:w-[160px]" style={{ height: totalHeight }}>
                <div className="absolute top-0 left-0 right-0 text-center">
                  <div className={`text-[10px] font-bold uppercase tracking-wider ${ROUND_COLORS[roundNumber] || 'text-white/40'}`}>
                    {roundLabel}
                  </div>
                </div>
                {renderedMatchups.map((matchup, index) => {
                  const top = topOffset + roundSlots[index] * rowHeight;
                  return (
                    <div
                      key={matchup.position}
                      className="absolute left-0 right-0"
                      style={{ top, height: cardHeight }}
                    >
                      <MatchupCard matchup={matchup} isMe={isMe} compact={isCompact} />
                    </div>
                  );
                })}
              </div>
              <ConnectorBridge
                fromSlots={roundSlots}
                toSlots={nextSlots}
                rowHeight={rowHeight}
                cardHeight={cardHeight}
                topOffset={topOffset}
                bridgeWidth={bridgeWidth}
              />
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
            <div className="flex flex-col justify-center items-center pl-2 sm:pl-4" style={{ width: '120px' }}>
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
  const [showRules, setShowRules] = useState(false);
  const { profile } = useAuth();

  const contestRules = [
    'Weekend Battles run only when there are 4 scheduled matches across Saturday and Sunday.',
    'The last match before Saturday becomes the qualifier and seeds the top 16 users.',
    'Each weekend match is a knockout round: Round of 16, Quarter Finals, Semi Finals, then Final.',
    'If scores are tied, the higher overall leaderboard rank wins the head-to-head.',
    'The winner of the Final is crowned Weekend Champion.',
  ];

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
    return m ? `M${matchId} - ${m.team1} vs ${m.team2}` : `M${matchId}`;
  };

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold text-white">Weekend Battle</h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowRules(true)}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-white/70 transition hover:bg-white/10 hover:text-white"
          >
            What's this?
          </button>
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

      {showRules && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-4 py-6 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-3xl border border-white/10 bg-[#07130d]/98 shadow-2xl shadow-black/60">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-purple-300">Weekend Battle</p>
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
              {contestRules.map((rule, index) => (
                <div key={index} className="flex gap-3 rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5">
                  <span className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-purple-500/20 text-[11px] font-bold text-purple-300">
                    {index + 1}
                  </span>
                  <span>{rule}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
