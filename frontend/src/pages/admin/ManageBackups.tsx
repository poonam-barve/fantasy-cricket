import { useEffect, useMemo, useState } from 'react';
import client from '../../api/client';

type BackupRow = {
  user_id: number;
  user_name: string;
  user_email?: string;
  match_id: number;
  team1: string;
  team2: string;
  match_date: string;
  backup_order: number;
  backup_player_id: number;
  backup_player_name: string;
  backup_team: string;
  backup_role: string;
  replaced_player_id?: number | null;
  replaced_player_name?: string | null;
  replaced_team?: string | null;
  replaced_role?: string | null;
  was_replaced: boolean;
  is_active_in_cached_team: boolean;
};

export default function ManageBackups() {
  const [rows, setRows] = useState<BackupRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [matchFilter, setMatchFilter] = useState('');
  const [userFilter, setUserFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'used' | 'unused'>('all');

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const res = await client.get('/api/admin/backups');
        setRows(res.data || []);
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, []);

  const matches = useMemo(() => {
    const unique = new Map<number, BackupRow>();
    rows.forEach((row) => unique.set(row.match_id, row));
    return [...unique.values()].sort((a, b) => b.match_id - a.match_id);
  }, [rows]);

  const filtered = rows.filter((row) => {
    if (matchFilter && row.match_id !== Number(matchFilter)) return false;
    if (userFilter && !row.user_name.toLowerCase().includes(userFilter.toLowerCase())) return false;
    if (statusFilter === 'used' && !row.was_replaced) return false;
    if (statusFilter === 'unused' && row.was_replaced) return false;
    return true;
  });

  const grouped = filtered.reduce<Record<string, BackupRow[]>>((acc, row) => {
    const key = `${row.match_id}-${row.user_id}`;
    acc[key] = acc[key] || [];
    acc[key].push(row);
    return acc;
  }, {});

  if (loading) return <div className="text-slate-300">Loading backups...</div>;

  return (
    <div className="space-y-6 text-slate-100">
      <div>
        <h1 className="text-2xl font-bold">Backups</h1>
        <p className="text-sm text-slate-400">Review backup order, replacement status, and cached active teams.</p>
      </div>

      <div className="grid gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4 md:grid-cols-3">
        <select value={matchFilter} onChange={(e) => setMatchFilter(e.target.value)} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm">
          <option value="">All matches</option>
          {matches.map((match) => (
            <option key={match.match_id} value={match.match_id}>
              M{match.match_id}: {match.team1} vs {match.team2}
            </option>
          ))}
        </select>
        <input
          value={userFilter}
          onChange={(e) => setUserFilter(e.target.value)}
          placeholder="Search user"
          className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
        />
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as 'all' | 'used' | 'unused')} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm">
          <option value="all">All statuses</option>
          <option value="used">Used backups</option>
          <option value="unused">Unused backups</option>
        </select>
      </div>

      <div className="grid gap-4">
        {Object.entries(grouped).map(([key, backups]) => {
          const first = backups[0];
          return (
            <div key={key} className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
                <div>
                  <p className="font-semibold">{first.user_name}</p>
                  <p className="text-xs text-slate-500">M{first.match_id} | {first.team1} vs {first.team2} | {first.match_date}</p>
                </div>
                <div className="text-xs text-slate-400">
                  {backups.filter((row) => row.was_replaced).length}/{backups.length} used
                </div>
              </div>
              <div className="divide-y divide-slate-800">
                {backups.map((row) => (
                  <div key={`${row.match_id}-${row.user_id}-${row.backup_order}`} className="grid gap-3 px-4 py-3 text-sm md:grid-cols-[4rem_1fr_1fr_auto]">
                    <div className="font-bold text-slate-400">#{row.backup_order}</div>
                    <div>
                      <p className="font-semibold text-slate-100">{row.backup_player_name}</p>
                      <p className="text-xs text-slate-500">{row.backup_team} | {row.backup_role}</p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500">Replaced</p>
                      <p className={row.was_replaced ? 'font-semibold text-amber-300' : 'text-slate-500'}>
                        {row.replaced_player_name || 'Not used'}
                      </p>
                      {row.replaced_player_name && <p className="text-xs text-slate-500">{row.replaced_team} | {row.replaced_role}</p>}
                    </div>
                    <div className="flex items-center gap-2 md:justify-end">
                      <span className={`rounded-full px-2 py-1 text-xs font-semibold ${row.was_replaced ? 'bg-amber-500/15 text-amber-300' : 'bg-slate-800 text-slate-400'}`}>
                        {row.was_replaced ? 'Used' : 'Unused'}
                      </span>
                      <span className={`rounded-full px-2 py-1 text-xs font-semibold ${row.is_active_in_cached_team ? 'bg-emerald-500/15 text-emerald-300' : 'bg-slate-800 text-slate-400'}`}>
                        {row.is_active_in_cached_team ? 'In cached XI' : 'Not in XI'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
        {filtered.length === 0 && (
          <div className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-8 text-center text-sm text-slate-500">
            No backups match the filters.
          </div>
        )}
      </div>
    </div>
  );
}
