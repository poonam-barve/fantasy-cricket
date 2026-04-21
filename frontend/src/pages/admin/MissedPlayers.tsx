import { useEffect, useMemo, useState } from 'react';
import client from '../../api/client';
import type { Match } from '../../types';

type MissedPlayerRow = {
  match_id: number;
  player_id: number;
  name: string;
  team: string;
  role: string;
  points: number;
  owner_count: number;
};

type MissedPlayersResponse = {
  match: Match | null;
  players: MissedPlayerRow[];
  missed_count: number;
  total_missed_points: number;
};

const formatRole = (role: string) => (role === 'AllRounder' ? 'All Rounder' : role);

export default function MissedPlayersPage() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [selectedMatchId, setSelectedMatchId] = useState<number | ''>('');
  const [data, setData] = useState<MissedPlayersResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = async (matchId?: number) => {
    const query = matchId ? `?match_id=${matchId}` : '';
    const res = await client.get(`/api/admin/missed-players${query}`);
    setData(res.data);
    if (!matchId && res.data?.match?.id) {
      setSelectedMatchId(res.data.match.id);
    }
  };

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [matchesRes, missedRes] = await Promise.all([
          client.get('/api/admin/matches'),
          client.get('/api/admin/missed-players'),
        ]);
        setMatches(matchesRes.data || []);
        setData(missedRes.data);
        if (missedRes.data?.match?.id) {
          setSelectedMatchId(missedRes.data.match.id);
        } else if ((matchesRes.data || []).length > 0) {
          setSelectedMatchId(matchesRes.data[matchesRes.data.length - 1].id);
        }
      } catch (err) {
        console.error('Failed to load missed players', err);
      } finally {
        setLoading(false);
      }
    };

    load();
  }, []);

  const rows = useMemo(() => data?.players || [], [data]);
  const selectedMatch = matches.find((match) => match.id === selectedMatchId) || data?.match || null;
  const topMissed = rows[0];

  const handleRefresh = async () => {
    if (!selectedMatchId) return;
    setRefreshing(true);
    try {
      await fetchData(Number(selectedMatchId));
    } finally {
      setRefreshing(false);
    }
  };

  const handleMatchChange = async (value: string) => {
    const nextId = value ? Number(value) : '';
    setSelectedMatchId(nextId);
    if (nextId) {
      setRefreshing(true);
      try {
        await fetchData(nextId);
      } finally {
        setRefreshing(false);
      }
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-indigo-600" />
      </div>
    );
  }

  return (
    <div className="text-slate-900">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Missed Players</h1>
          <p className="text-sm text-gray-500">Players with zero owners in the selected match.</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={selectedMatchId}
            onChange={(e) => handleMatchChange(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 min-w-[16rem]"
          >
            <option value="">Select match...</option>
            {matches.map((match) => (
              <option key={match.id} value={match.id}>
                #{match.id} {match.team1} vs {match.team2}
              </option>
            ))}
          </select>
          <button
            onClick={handleRefresh}
            disabled={refreshing || !selectedMatchId}
            className="inline-flex items-center gap-2 bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {refreshing ? (
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            )}
            Refresh
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="bg-white rounded-2xl shadow-sm p-5">
          <p className="text-sm text-gray-500">Missed Players</p>
          <p className="text-3xl font-bold text-gray-800 mt-1">{data?.missed_count || 0}</p>
        </div>
        <div className="bg-white rounded-2xl shadow-sm p-5">
          <p className="text-sm text-gray-500">Missed Points</p>
          <p className="text-3xl font-bold text-gray-800 mt-1">{(data?.total_missed_points || 0).toFixed(2)}</p>
        </div>
        <div className="bg-white rounded-2xl shadow-sm p-5">
          <p className="text-sm text-gray-500">Match</p>
          <p className="text-base font-semibold text-gray-800 mt-1">
            {selectedMatch ? `#${selectedMatch.id} ${selectedMatch.team1} vs ${selectedMatch.team2}` : 'No match selected'}
          </p>
        </div>
      </div>

      <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold text-gray-800">Missed Players Table</h2>
              <p className="text-sm text-gray-500">Players who were not picked by any active user in this match.</p>
            </div>
            {topMissed && (
              <div className="text-right">
                <p className="text-xs text-gray-400">Top missed player</p>
                <p className="text-sm font-semibold text-gray-800">{topMissed.name}</p>
              </div>
            )}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="bg-gray-50 text-gray-600 uppercase text-xs">
              <tr>
                <th className="px-6 py-3">Player</th>
                <th className="px-6 py-3">Team</th>
                <th className="px-6 py-3">Role</th>
                <th className="px-6 py-3 text-right">Points</th>
                <th className="px-6 py-3 text-right">Owners</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((row) => (
                <tr key={`${row.match_id}-${row.player_id}`} className="hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4">
                    <div className="font-medium text-gray-800">{row.name}</div>
                    <div className="text-xs text-gray-400">Player #{row.player_id}</div>
                  </td>
                  <td className="px-6 py-4">
                    <span className="inline-block bg-indigo-100 text-indigo-700 text-xs font-semibold px-2 py-1 rounded-full">
                      {row.team}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-gray-600">{formatRole(row.role)}</td>
                  <td className="px-6 py-4 text-right font-semibold text-gray-800">{row.points.toFixed(2)}</td>
                  <td className="px-6 py-4 text-right">
                    <span className="inline-flex items-center rounded-full bg-rose-100 px-2.5 py-1 text-xs font-semibold text-rose-700">
                      {row.owner_count}
                    </span>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-6 py-10 text-center text-gray-400">
                    No missed players for this match.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
