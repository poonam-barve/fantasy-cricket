import { useEffect, useState } from 'react';
import client from '../../api/client';
import type { User, Player, Match } from '../../types';

export default function AdminDashboard() {
  const [users, setUsers] = useState<User[]>([]);
  const [players, setPlayers] = useState<Player[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [recalculating, setRecalculating] = useState(false);
  const [recalcMsg, setRecalcMsg] = useState<string | null>(null);

  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [uRes, pRes, mRes] = await Promise.all([
          client.get('/api/admin/users'),
          client.get('/api/admin/players'),
          client.get('/api/admin/matches'),
        ]);
        setUsers(uRes.data);
        setPlayers(pRes.data);
        setMatches(mRes.data);
      } catch (err) {
        console.error('Failed to fetch dashboard data', err);
      } finally {
        setLoading(false);
      }
    };
    fetchAll();
  }, []);

  const liveCount = matches.filter((m) => m.status === 'live').length;

  const stats = [
    {
      label: 'Total Users',
      value: users.length,
      color: 'bg-blue-500',
      icon: (
        <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m9-4a4 4 0 10-8 0 4 4 0 008 0zm6 4a4 4 0 10-8 0 4 4 0 008 0z" />
        </svg>
      ),
    },
    {
      label: 'Total Players',
      value: players.length,
      color: 'bg-emerald-500',
      icon: (
        <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
      ),
    },
    {
      label: 'Total Matches',
      value: matches.length,
      color: 'bg-amber-500',
      icon: (
        <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
      ),
    },
    {
      label: 'Live Matches',
      value: liveCount,
      color: 'bg-red-500',
      icon: (
        <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.636 18.364a9 9 0 1012.728 0M12 9v4l3 3" />
        </svg>
      ),
    },
  ];

  const handleRecalculate = async () => {
    setRecalculating(true);
    setRecalcMsg(null);
    try {
      await client.post('/api/admin/achievements/recalculate');
      setRecalcMsg('Achievements recalculated successfully');
    } catch {
      setRecalcMsg('Failed to recalculate');
    } finally {
      setRecalculating(false);
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
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Dashboard</h1>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-6">
        {stats.map((stat) => (
          <div
            key={stat.label}
            className="bg-white rounded-2xl shadow-sm p-6 flex items-center gap-4 hover:shadow-md transition-shadow"
          >
            <div className={`${stat.color} rounded-xl p-3 flex-shrink-0`}>
              {stat.icon}
            </div>
            <div>
              <p className="text-sm text-gray-500 font-medium">{stat.label}</p>
              <p className="text-3xl font-bold text-gray-800">{stat.value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Admin Actions */}
      <h2 className="text-lg font-bold text-gray-800 mt-8 mb-4">Actions</h2>
      <div className="flex flex-wrap gap-3">
        <button
          onClick={handleRecalculate}
          disabled={recalculating}
          className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {recalculating ? 'Recalculating...' : 'Recalculate Achievements'}
        </button>
      </div>
      {recalcMsg && (
        <p className={`mt-2 text-sm ${recalcMsg.includes('Failed') ? 'text-red-600' : 'text-green-600'}`}>
          {recalcMsg}
        </p>
      )}
    </div>
  );
}
