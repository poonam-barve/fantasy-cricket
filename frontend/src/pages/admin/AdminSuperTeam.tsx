import { useEffect, useMemo, useState } from 'react';
import client from '../../api/client';
import type { Player, User } from '../../types';

type Role = 'Wicketkeeper' | 'Batter' | 'AllRounder' | 'Bowler';
type Submission = { user_id: number; name: string; player_ids: number[]; updated_at?: string | null };
type Standing = { user_id: number; name: string; points: number; rank: number };

const roles: Role[] = ['Wicketkeeper', 'Batter', 'AllRounder', 'Bowler'];
const requiredRoles: Role[] = ['Wicketkeeper', 'Batter', 'AllRounder'];
const SUPER_TEAM_SIZE = 12;
const PLAYERS_PER_TEAM = 3;
const MIN_BOWLERS = 3;

function apiErrorDetail(error: unknown, fallback: string) {
  const response = (error as { response?: { data?: { detail?: unknown } } } | null)?.response;
  return typeof response?.data?.detail === 'string' ? response.data.detail : fallback;
}

export default function AdminSuperTeam() {
  const [users, setUsers] = useState<User[]>([]);
  const [playersByRole, setPlayersByRole] = useState<Record<Role, Player[]>>({
    Wicketkeeper: [],
    Batter: [],
    AllRounder: [],
    Bowler: [],
  });
  const [teams, setTeams] = useState<Submission[]>([]);
  const [standings, setStandings] = useState<Standing[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<number | ''>('');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [activeRole, setActiveRole] = useState<Role>('Wicketkeeper');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [superRes, usersRes] = await Promise.all([
        client.get('/api/admin/super-team'),
        client.get('/api/admin/users'),
      ]);
      setPlayersByRole(superRes.data.players || {});
      setTeams(superRes.data.teams || []);
      setStandings(superRes.data.standings || []);
      setUsers(usersRes.data || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!selectedUserId) {
      setSelected(new Set());
      return;
    }
    const existing = teams.find((team) => team.user_id === Number(selectedUserId));
    setSelected(new Set(existing?.player_ids || []));
  }, [selectedUserId, teams]);

  const allPlayers = useMemo(() => roles.flatMap((role) => playersByRole[role] || []), [playersByRole]);
  const selectedPlayers = allPlayers.filter((player) => selected.has(player.id));
  const bowlerCount = selectedPlayers.filter((player) => player.role === 'Bowler').length;
  const roleCounts = selectedPlayers.reduce<Record<Role, number>>((acc, player) => {
    if (roles.includes(player.role as Role)) {
      const role = player.role as Role;
      acc[role] = (acc[role] || 0) + 1;
    }
    return acc;
  }, {
    Wicketkeeper: 0,
    Batter: 0,
    AllRounder: 0,
    Bowler: 0,
  });
  const teamCounts = selectedPlayers.reduce<Record<string, number>>((acc, player) => {
    acc[player.team] = (acc[player.team] || 0) + 1;
    return acc;
  }, {});
  const eligibleTeams = [...new Set(allPlayers.map((player) => player.team))];
  const invalidTeams = eligibleTeams.filter((team) => (teamCounts[team] || 0) !== PLAYERS_PER_TEAM);
  const missingRoles = requiredRoles.filter((role) => (roleCounts[role] || 0) < 1);
  const validationMessage = (() => {
    if (selected.size !== SUPER_TEAM_SIZE) return `Select exactly ${SUPER_TEAM_SIZE} players.`;
    if (missingRoles.length > 0) return 'Select at least 1 Wicketkeeper, 1 Batter, and 1 AllRounder.';
    if (bowlerCount < MIN_BOWLERS) return `Select at least ${MIN_BOWLERS} Bowlers.`;
    if (invalidTeams.length > 0) return `Select exactly ${PLAYERS_PER_TEAM} players from each playoff team.`;
    return '';
  })();

  const toggle = (playerId: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(playerId)) next.delete(playerId);
      else if (next.size < SUPER_TEAM_SIZE) next.add(playerId);
      return next;
    });
  };

  const save = async () => {
    if (!selectedUserId) {
      setMessage('Select a user first.');
      return;
    }
    if (validationMessage) {
      setMessage(validationMessage);
      return;
    }
    setSaving(true);
    setMessage('');
    try {
      await client.put('/api/admin/super-team', {
        user_id: selectedUserId,
        players: [...selected],
      });
      setMessage('Super Team updated.');
      await load();
    } catch (err: unknown) {
      setMessage(apiErrorDetail(err, 'Failed to update Super Team.'));
    } finally {
      setSaving(false);
    }
  };

  const recalc = async () => {
    setSaving(true);
    try {
      await client.post('/api/admin/super-team/recalculate');
      setMessage('Super Team standings recalculated.');
      await load();
    } catch {
      setMessage('Failed to recalculate standings.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="text-slate-300">Loading Super Team admin...</div>;

  return (
    <div className="space-y-6 text-slate-100">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Super Team</h1>
          <p className="text-sm text-slate-400">Admin edits obey the same 12-player rules and can be saved after lock.</p>
        </div>
        <button onClick={recalc} disabled={saving} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
          Recalculate
        </button>
      </div>

      {message && <div className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-slate-200">{message}</div>}

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <div className="mb-4 grid gap-3 sm:grid-cols-[1fr_auto]">
            <select value={selectedUserId} onChange={(e) => setSelectedUserId(e.target.value ? Number(e.target.value) : '')} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100">
              <option value="">Select user</option>
              {users.map((user) => <option key={user.id} value={user.id}>{user.name}</option>)}
            </select>
            <button onClick={save} disabled={saving || !selectedUserId || Boolean(validationMessage)} className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
              Save Team
            </button>
          </div>

          <div className="mb-4 grid gap-2 sm:grid-cols-4">
            <Metric label="Selected" value={`${selected.size}/${SUPER_TEAM_SIZE}`} good={selected.size === SUPER_TEAM_SIZE} />
            <Metric label="Bowlers" value={`${bowlerCount}/${MIN_BOWLERS}`} good={bowlerCount >= MIN_BOWLERS} />
            <Metric label="Team Splits" value={invalidTeams.length === 0 ? 'OK' : `${invalidTeams.length} off`} good={invalidTeams.length === 0} />
            <Metric label="Role Splits" value={missingRoles.length === 0 ? 'OK' : `${missingRoles.length} missing`} good={missingRoles.length === 0} />
          </div>

          <div className="mb-4 flex gap-1 rounded-lg bg-slate-950 p-1">
            {roles.map((role) => (
              <button key={role} onClick={() => setActiveRole(role)} className={`flex-1 rounded-md px-2 py-2 text-xs font-semibold ${activeRole === role ? 'bg-white text-slate-950' : 'text-slate-400'}`}>
                {role === 'Wicketkeeper' ? 'WK' : role === 'Batter' ? 'BAT' : role === 'AllRounder' ? 'AR' : 'BALL'}
              </button>
            ))}
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            {(playersByRole[activeRole] || []).map((player) => {
              const picked = selected.has(player.id);
              return (
                <button key={player.id} onClick={() => toggle(player.id)} className={`rounded-lg border p-3 text-left ${picked ? 'border-emerald-400 bg-emerald-500/10' : 'border-slate-800 bg-slate-950 hover:bg-slate-800'}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold">{player.name}</p>
                      <p className="text-xs text-slate-400">{player.team} | {player.role}</p>
                    </div>
                    <span className="text-xs font-bold">{picked ? 'Picked' : '+'}</span>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">{player.total_points || 0} pts | {player.avg_points || 0} avg</p>
                </button>
              );
            })}
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-slate-800 bg-slate-900">
            <div className="border-b border-slate-800 px-4 py-3 text-sm font-semibold">Standings</div>
            <div className="divide-y divide-slate-800">
              {standings.map((row) => (
                <div key={row.user_id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                  <span>#{row.rank} {row.name}</span>
                  <span className="font-bold text-blue-300">{row.points}</span>
                </div>
              ))}
              {standings.length === 0 && <div className="px-4 py-6 text-sm text-slate-500">No standings yet.</div>}
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900">
            <div className="border-b border-slate-800 px-4 py-3 text-sm font-semibold">Submitted Teams</div>
            <div className="max-h-96 divide-y divide-slate-800 overflow-auto">
              {teams.map((team) => (
                <button key={team.user_id} onClick={() => setSelectedUserId(team.user_id)} className="block w-full px-4 py-3 text-left text-sm hover:bg-slate-800">
                  <p className="font-medium">{team.name}</p>
                  <p className="text-xs text-slate-500">{team.player_ids.length} players | {team.updated_at || '-'}</p>
                </button>
              ))}
              {teams.length === 0 && <div className="px-4 py-6 text-sm text-slate-500">No submitted teams.</div>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value, good }: { label: string; value: string; good: boolean }) {
  return (
    <div className="rounded-lg bg-slate-950 p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`text-lg font-bold ${good ? 'text-emerald-300' : 'text-amber-300'}`}>{value}</p>
    </div>
  );
}
