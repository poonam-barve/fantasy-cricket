import { useEffect, useMemo, useState } from 'react';
import client from '../../api/client';
import type { Player, User } from '../../types';

type Role = 'Wicketkeeper' | 'Batter' | 'AllRounder' | 'Bowler';
type Submission = { user_id: number; name: string; player_ids: number[]; captain?: number | null; vice_captain?: number | null; updated_at?: string | null };
type Standing = { user_id: number; name: string; points: number; rank: number };
type SnapshotPhase = 'current' | 'original' | 'edited' | 'final';
type SnapshotMap = Record<SnapshotPhase, Submission[]>;

const roles: Role[] = ['Wicketkeeper', 'Batter', 'AllRounder', 'Bowler'];
const requiredRoles: Role[] = ['Wicketkeeper', 'Batter', 'AllRounder'];
const SUPER_TEAM_SIZE = 12;
const MIN_BOWLERS = 4;
const snapshotPhases: { key: SnapshotPhase; label: string; helper: string }[] = [
  { key: 'current', label: 'Current Draft', helper: 'Editable live/draft team' },
  { key: 'original', label: 'Original', helper: 'Matches 71-72' },
  { key: 'edited', label: 'Edited', helper: 'Match 73' },
  { key: 'final', label: 'Final', helper: 'Match 74' },
];

function apiErrorDetail(error: unknown, fallback: string) {
  const response = (error as { response?: { data?: { detail?: unknown } } } | null)?.response;
  return typeof response?.data?.detail === 'string' ? response.data.detail : fallback;
}

function fallbackPhases(phase: SnapshotPhase): SnapshotPhase[] {
  if (phase === 'final') return ['final', 'edited', 'original', 'current'];
  if (phase === 'edited') return ['edited', 'original', 'current'];
  if (phase === 'original') return ['original', 'current'];
  return ['current'];
}

function findTeamForPhase(snapshots: SnapshotMap, teams: Submission[], phase: SnapshotPhase, userId: number) {
  const snapshotMap = { ...snapshots, current: snapshots.current?.length ? snapshots.current : teams };
  for (const candidatePhase of fallbackPhases(phase)) {
    const existing = (snapshotMap[candidatePhase] || []).find((team) => team.user_id === userId);
    if (existing) return existing;
  }
  return null;
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
  const [snapshots, setSnapshots] = useState<SnapshotMap>({ current: [], original: [], edited: [], final: [] });
  const [standings, setStandings] = useState<Standing[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<number | ''>('');
  const [activePhase, setActivePhase] = useState<SnapshotPhase>('current');
  const [viewPhase, setViewPhase] = useState<SnapshotPhase>('current');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [captain, setCaptain] = useState<number | null>(null);
  const [viceCaptain, setViceCaptain] = useState<number | null>(null);
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
      setSnapshots({
        current: superRes.data.snapshots?.current || superRes.data.teams || [],
        original: superRes.data.snapshots?.original || [],
        edited: superRes.data.snapshots?.edited || [],
        final: superRes.data.snapshots?.final || [],
      });
      setStandings(superRes.data.standings || []);
      setUsers(usersRes.data || []);
      const effectivePhase = superRes.data.effective_admin_phase as SnapshotPhase | undefined;
      if (effectivePhase && snapshotPhases.some((phase) => phase.key === effectivePhase)) {
        setActivePhase(effectivePhase);
        setViewPhase(effectivePhase);
      }
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
      setCaptain(null);
      setViceCaptain(null);
      return;
    }
    const existing = findTeamForPhase(snapshots, teams, activePhase, Number(selectedUserId));
    setSelected(new Set(existing?.player_ids || []));
    setCaptain(existing?.captain ? Number(existing.captain) : null);
    setViceCaptain(existing?.vice_captain ? Number(existing.vice_captain) : null);
  }, [activePhase, selectedUserId, snapshots, teams]);

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
  const missingRoles = requiredRoles.filter((role) => (roleCounts[role] || 0) < 1);
  const validationMessage = (() => {
    if (selected.size !== SUPER_TEAM_SIZE) return `Select exactly ${SUPER_TEAM_SIZE} players.`;
    if (missingRoles.length > 0) return 'Select at least 1 Wicketkeeper, 1 Batter, and 1 AllRounder.';
    if (bowlerCount < MIN_BOWLERS) return `Select at least ${MIN_BOWLERS} Bowlers.`;
    if (!captain || !selected.has(captain)) return 'Select a Captain.';
    if (!viceCaptain || !selected.has(viceCaptain)) return 'Select a Vice-Captain.';
    if (captain === viceCaptain) return 'Captain and Vice-Captain must be different.';
    return '';
  })();

  const toggle = (playerId: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(playerId)) {
        next.delete(playerId);
        if (captain === playerId) setCaptain(null);
        if (viceCaptain === playerId) setViceCaptain(null);
      }
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
        captain,
        vice_captain: viceCaptain,
        phase: activePhase,
      });
      setMessage(`${snapshotPhases.find((phase) => phase.key === activePhase)?.label || 'Super Team'} updated.`);
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
          <p className="text-sm text-slate-400">Edit current drafts or phase snapshots for Matches 71-74.</p>
        </div>
        <button onClick={recalc} disabled={saving} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
          Recalculate
        </button>
      </div>

      {message && <div className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-slate-200">{message}</div>}

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <div className="mb-4 grid gap-2 sm:grid-cols-4">
            {snapshotPhases.map((phase) => (
              <button
                key={phase.key}
                type="button"
                onClick={() => {
                  setActivePhase(phase.key);
                  setViewPhase(phase.key);
                }}
                className={`rounded-lg border px-3 py-2 text-left transition ${
                  activePhase === phase.key ? 'border-emerald-400 bg-emerald-500/10' : 'border-slate-800 bg-slate-950 hover:bg-slate-800'
                }`}
              >
                <p className="text-sm font-semibold">{phase.label}</p>
                <p className="text-[11px] text-slate-500">{phase.helper}</p>
              </button>
            ))}
          </div>

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
            <Metric label="Teams Used" value={String(Object.keys(teamCounts).length)} good={selected.size > 0} />
            <Metric label="Role Splits" value={missingRoles.length === 0 ? 'OK' : `${missingRoles.length} missing`} good={missingRoles.length === 0} />
            <Metric label="C / VC" value={`${(captain ? 1 : 0) + (viceCaptain ? 1 : 0)}/2`} good={Boolean(captain && viceCaptain && captain !== viceCaptain)} />
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
              const isCaptain = captain === player.id;
              const isViceCaptain = viceCaptain === player.id;
              return (
                <button key={player.id} onClick={() => toggle(player.id)} className={`rounded-lg border p-3 text-left ${picked ? 'border-emerald-400 bg-emerald-500/10' : 'border-slate-800 bg-slate-950 hover:bg-slate-800'}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold">{player.name}</p>
                      <p className="text-xs text-slate-400">{player.team} | {player.role}</p>
                    </div>
                    <div className="flex flex-shrink-0 items-center gap-1">
                      {picked && (
                        <>
                          <span
                            onClick={(event) => {
                              event.stopPropagation();
                              setCaptain((current) => (current === player.id ? null : player.id));
                              if (viceCaptain === player.id) setViceCaptain(null);
                            }}
                            className={`rounded px-2 py-1 text-xs font-bold ${isCaptain ? 'bg-amber-400 text-slate-950' : 'bg-slate-800 text-slate-400'}`}
                          >
                            C
                          </span>
                          <span
                            onClick={(event) => {
                              event.stopPropagation();
                              setViceCaptain((current) => (current === player.id ? null : player.id));
                              if (captain === player.id) setCaptain(null);
                            }}
                            className={`rounded px-2 py-1 text-xs font-bold ${isViceCaptain ? 'bg-cyan-400 text-slate-950' : 'bg-slate-800 text-slate-400'}`}
                          >
                            VC
                          </span>
                        </>
                      )}
                      <span className="text-xs font-bold">{picked ? 'Picked' : '+'}</span>
                    </div>
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
            <div className="border-b border-slate-800 px-4 py-3">
              <div className="mb-3 text-sm font-semibold">Teams By Snapshot</div>
              <div className="grid grid-cols-2 gap-1 rounded-lg bg-slate-950 p-1">
                {snapshotPhases.map((phase) => (
                  <button
                    key={phase.key}
                    type="button"
                    onClick={() => setViewPhase(phase.key)}
                    className={`rounded-md px-2 py-1.5 text-[11px] font-semibold ${
                      viewPhase === phase.key ? 'bg-white text-slate-950' : 'text-slate-400 hover:bg-slate-800'
                    }`}
                  >
                    {phase.label} ({(snapshots[phase.key] || []).length})
                  </button>
                ))}
              </div>
            </div>
            <div className="max-h-96 divide-y divide-slate-800 overflow-auto">
              {(snapshots[viewPhase] || []).map((team) => (
                <button
                  key={`${viewPhase}-${team.user_id}`}
                  onClick={() => {
                    setActivePhase(viewPhase);
                    setSelectedUserId(team.user_id);
                  }}
                  className="block w-full px-4 py-3 text-left text-sm hover:bg-slate-800"
                >
                  <p className="font-medium">{team.name}</p>
                  <p className="text-xs text-slate-500">{team.player_ids.length} players | C {team.captain || '-'} | VC {team.vice_captain || '-'} | {team.updated_at || (team as any).snapshot_at || '-'}</p>
                </button>
              ))}
              {(snapshots[viewPhase] || []).length === 0 && <div className="px-4 py-6 text-sm text-slate-500">No teams in this snapshot.</div>}
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
