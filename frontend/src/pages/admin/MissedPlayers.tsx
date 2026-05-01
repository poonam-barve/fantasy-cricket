import { useEffect, useMemo, useState } from 'react';
import client from '../../api/client';
import type { Match } from '../../types';

type MissedPlayerRow = {
  match_id: number;
  name: string;
  team: string;
  match_date: string;
  team1: string;
  team2: string;
};

type MissedPlayersResponse = {
  match: Match | null;
  players: MissedPlayerRow[];
  missed_count: number;
};

export default function MissedPlayersPage() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [data, setData] = useState<MissedPlayersResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = async () => {
    const res = await client.get(`/api/admin/missed-players`);
    setData(res.data);
  };

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const matchesRes = await client.get('/api/admin/matches');
        setMatches(matchesRes.data || []);
        await fetchData();
      } catch (err) {
        console.error('Failed to load missed players', err);
      } finally {
        setLoading(false);
      }
    };

    load();
  }, []);

  const rows = useMemo(() => data?.players || [], [data]);
  const affectedMatches = useMemo(() => new Set(rows.map((row) => row.match_id)).size, [rows]);
  const latestUnmapped = rows[0];

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
          <p className="text-sm text-gray-500">Parsed scorecard names that could not be matched to our player list.</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2">
            <button
              onClick={handleRefresh}
              disabled={refreshing}
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
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="bg-white rounded-2xl shadow-sm p-5">
          <p className="text-sm text-gray-500">Unmapped Players</p>
          <p className="text-3xl font-bold text-gray-800 mt-1">{data?.missed_count || 0}</p>
        </div>
        <div className="bg-white rounded-2xl shadow-sm p-5">
          <p className="text-sm text-gray-500">Matches Affected</p>
          <p className="text-3xl font-bold text-gray-800 mt-1">{affectedMatches}</p>
        </div>
        <div className="bg-white rounded-2xl shadow-sm p-5">
          <p className="text-sm text-gray-500">Match</p>
          <p className="text-base font-semibold text-gray-800 mt-1">All matches</p>
          <p className="text-xs text-gray-500 mt-1">Showing unmapped players across all matches. Match numbers are shown per row.</p>
        </div>
      </div>

      <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold text-gray-800">Missed Players Table</h2>
              <p className="text-sm text-gray-500">Parsed player names that still need a manual mapping in the registry.</p>
            </div>
            {latestUnmapped && (
              <div className="text-right">
                <p className="text-xs text-gray-400">Sample unmapped entry</p>
                <p className="text-sm font-semibold text-gray-800">{latestUnmapped.name}</p>
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
                <th className="px-6 py-3">Match</th>
                <th className="px-6 py-3">Match Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((row) => (
                <tr key={`${row.match_id}-${row.team}-${row.name}`} className="hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4">
                    <div className="font-medium text-gray-800">{row.name}</div>
                  </td>
                  <td className="px-6 py-4">
                    <span className="inline-block bg-indigo-100 text-indigo-700 text-xs font-semibold px-2 py-1 rounded-full">
                      {row.team}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-gray-600">
                    #{row.match_id} {row.team1} vs {row.team2}
                  </td>
                  <td className="px-6 py-4 text-gray-600">
                    {row.match_date || 'Unknown'}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-6 py-10 text-center text-gray-400">
                    No unmapped scorecard players for this match.
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
