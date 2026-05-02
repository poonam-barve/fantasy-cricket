import { useEffect, useState } from 'react';
import client from '../../api/client';
import type { Match } from '../../types';

interface Player { id: number; name: string; team: string; role: string; }
interface UserInfo { id: number; name: string; email?: string }

export default function ScoreControl() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);
  const [recalcAllLoading, setRecalcAllLoading] = useState(false);
  const [recalculating, setRecalculating] = useState<Record<number, boolean>>({});

  // Submit team
  const [selectedUserId, setSelectedUserId] = useState<number | ''>('');
  const [selectedMatchId, setSelectedMatchId] = useState<number | ''>('');
  const [selectedPlayers, setSelectedPlayers] = useState<Set<number>>(new Set());
  const [captainId, setCaptainId] = useState<number | null>(null);
  const [viceCaptainId, setViceCaptainId] = useState<number | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const [mRes, uRes] = await Promise.all([client.get('/api/admin/matches'), client.get('/api/admin/users')]);
        if (!mounted) return;
        setMatches(mRes.data || []);
        setUsers(uRes.data || []);
        // load players list (flat)
        const pRes = await client.get('/api/admin/players');
        if (!mounted) return;
        setPlayers(pRes.data || []);
      } catch (err) {
        console.error('Failed to load admin data', err);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    void load();
    return () => { mounted = false; };
  }, []);

  const recalcMatch = async (matchId: number) => {
    setRecalculating((s) => ({ ...s, [matchId]: true }));
    try {
      await client.post(`/api/admin/recalculate/${matchId}`);
      // success
    } catch (err) {
      console.error('recalc failed', err);
    } finally {
      setRecalculating((s) => ({ ...s, [matchId]: false }));
    }
  };

  const recalcAll = async () => {
    setRecalcAllLoading(true);
    try {
      const liveOrCompleted = matches.filter((m) => m.status === 'live' || m.status === 'completed');
      await Promise.all(liveOrCompleted.map((m) => client.post(`/api/admin/recalculate/${m.id}`)));
    } catch (err) {
      console.error('recalc all failed', err);
    } finally {
      setRecalcAllLoading(false);
    }
  };

  const togglePlayer = (pid: number) => {
    setSelectedPlayers((prev) => {
      const next = new Set(prev);
      if (next.has(pid)) {
        next.delete(pid);
        if (captainId === pid) setCaptainId(null);
        if (viceCaptainId === pid) setViceCaptainId(null);
      } else if (next.size < 11) {
        next.add(pid);
      }
      return next;
    });
  };

  const submitTeam = async () => {
    if (!selectedUserId || !selectedMatchId) return;
    if (selectedPlayers.size !== 11) return alert('Select 11 players');
    if (!captainId || !viceCaptainId) return alert('Select C and VC');
    if (captainId === viceCaptainId) return alert('C and VC must differ');

    setSubmitLoading(true);
    try {
      await client.post('/api/admin/teams/submit', {
        user_id: selectedUserId,
        match_id: selectedMatchId,
        players: Array.from(selectedPlayers).map((pid) => ({ player_id: pid, is_captain: pid === captainId, is_vice_captain: pid === viceCaptainId }))
      });
      alert('Team submitted');
      setSelectedPlayers(new Set());
      setCaptainId(null); setViceCaptainId(null);
    } catch (err) {
      console.error(err);
      alert('Submit failed');
    } finally {
      setSubmitLoading(false);
    }
  };

  if (loading) return <div className="p-6">Loading...</div>;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Score Control</h1>
        <div className="flex items-center gap-2">
          <button onClick={recalcAll} disabled={recalcAllLoading} className="px-4 py-2 bg-indigo-600 text-white rounded">
            {recalcAllLoading ? 'Working...' : 'Recalculate All'}
          </button>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 gap-4">
        {matches.map((m) => (
          <div key={m.id} className="p-4 border rounded bg-white">
            <div className="flex justify-between items-center">
              <div>
                <div className="font-semibold">#{m.id} {m.team1} vs {m.team2}</div>
                <div className="text-xs text-gray-600">{m.match_date} {m.match_time}</div>
              </div>
              <div>
                <button onClick={() => recalcMatch(m.id)} disabled={!!recalculating[m.id]} className="px-3 py-1 bg-gray-200 rounded">
                  {recalculating[m.id] ? '...' : 'Recalc'}
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="p-4 border rounded bg-white">
        <h2 className="font-semibold mb-2">Submit Team for User</h2>
        <div className="grid sm:grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-sm">User</label>
            <select value={selectedUserId} onChange={(e) => setSelectedUserId(e.target.value ? Number(e.target.value) : '')} className="w-full border p-2 rounded">
              <option value="">Select user</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm">Match</label>
            <select value={selectedMatchId} onChange={(e) => setSelectedMatchId(e.target.value ? Number(e.target.value) : '')} className="w-full border p-2 rounded">
              <option value="">Select match</option>
              {matches.map((m) => <option key={m.id} value={m.id}>#{m.id} {m.team1} vs {m.team2}</option>)}
            </select>
          </div>
        </div>

        <div className="mb-2">Players ({selectedPlayers.size}/11)</div>
        <div className="max-h-48 overflow-auto border rounded p-2 mb-4">
          {players.map((p) => {
            const checked = selectedPlayers.has(p.id);
            return (
              <label key={p.id} className="flex items-center justify-between gap-2 p-2 hover:bg-gray-50">
                <div>
                  <div className="font-medium">{p.name}</div>
                  <div className="text-xs text-gray-500">{p.team} • {p.role}</div>
                </div>
                <div className="flex items-center gap-2">
                  <input type="checkbox" checked={checked} onChange={() => togglePlayer(p.id)} />
                  <button disabled={!checked} onClick={() => setCaptainId(p.id)} className={`px-2 py-1 rounded ${captainId===p.id? 'bg-amber-500 text-white':''}`}>C</button>
                  <button disabled={!checked} onClick={() => setViceCaptainId(p.id)} className={`px-2 py-1 rounded ${viceCaptainId===p.id? 'bg-sky-500 text-white':''}`}>VC</button>
                </div>
              </label>
            );
          })}
        </div>

        <div className="flex justify-end gap-2">
          <button onClick={() => { setSelectedPlayers(new Set()); setCaptainId(null); setViceCaptainId(null); }} className="px-4 py-2 border rounded">Reset</button>
          <button onClick={submitTeam} disabled={submitLoading} className="px-4 py-2 bg-indigo-600 text-white rounded">{submitLoading ? 'Submitting...' : 'Submit Team'}</button>
        </div>
      </div>
    </div>
  );
}
