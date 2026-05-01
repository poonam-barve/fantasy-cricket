import { useEffect, useMemo, useState } from 'react';
import client from '../../api/client';
import type { AdminMatchWithTeamCount, AdminUserTeam, Player } from '../../types';

const ROLE_ORDER = ['Wicketkeeper', 'Batter', 'AllRounder', 'Bowler'];

type EditableSelection = {
  player_id: number;
  is_captain: boolean;
  is_vice_captain: boolean;
};

export default function ManageTeams() {
  const [matches, setMatches] = useState<AdminMatchWithTeamCount[]>([]);
  const [selectedMatchId, setSelectedMatchId] = useState<number | null>(null);
  const [teams, setTeams] = useState<AdminUserTeam[]>([]);
  const [players, setPlayers] = useState<Player[]>([]);
  const [loadingMatches, setLoadingMatches] = useState(true);
  const [loadingTeams, setLoadingTeams] = useState(false);
  const [editingTeam, setEditingTeam] = useState<AdminUserTeam | null>(null);
  const [selectedPlayers, setSelectedPlayers] = useState<Map<number, EditableSelection>>(new Map());
  const [saving, setSaving] = useState(false);

  const fetchMatches = async () => {
    try {
      const res = await client.get('/api/admin/teams/matches');
      const data: AdminMatchWithTeamCount[] = res.data || [];
      setMatches(data);
      if (data.length > 0 && !selectedMatchId) {
        const firstWithTeams = data.find((match) => match.team_count > 0) || data[0];
        setSelectedMatchId(firstWithTeams.id);
      }
    } catch (err) {
      console.error('Failed to fetch matches for teams admin', err);
    } finally {
      setLoadingMatches(false);
    }
  };

  const fetchTeams = async (matchId: number) => {
    setLoadingTeams(true);
    try {
      const [teamsRes, playersRes] = await Promise.all([
        client.get(`/api/admin/teams?match_id=${matchId}`),
        client.get(`/api/players?match_id=${matchId}`),
      ]);

      const teamsData = teamsRes.data?.teams || [];
      setTeams(teamsData);

      const playersData = playersRes.data?.players || playersRes.data || {};
      const flatPlayers = Array.isArray(playersData)
        ? playersData
        : Object.values(playersData).flat() as Player[];
      setPlayers(flatPlayers);
    } catch (err) {
      console.error('Failed to fetch teams for match', err);
      setTeams([]);
      setPlayers([]);
    } finally {
      setLoadingTeams(false);
    }
  };

  useEffect(() => {
    fetchMatches();
  }, []);

  useEffect(() => {
    if (selectedMatchId) {
      fetchTeams(selectedMatchId);
    }
  }, [selectedMatchId]);

  const openEdit = (team: AdminUserTeam) => {
    const next = new Map<number, EditableSelection>();
    team.players.forEach((player) => {
      next.set(player.player_id, {
        player_id: player.player_id,
        is_captain: player.is_captain,
        is_vice_captain: player.is_vice_captain,
      });
    });
    setSelectedPlayers(next);
    setEditingTeam(team);
  };

  const closeEdit = () => {
    setEditingTeam(null);
    setSelectedPlayers(new Map());
  };

  const togglePlayer = (playerId: number) => {
    setSelectedPlayers((prev) => {
      const next = new Map(prev);
      if (next.has(playerId)) next.delete(playerId);
      else next.set(playerId, { player_id: playerId, is_captain: false, is_vice_captain: false });
      return next;
    });
  };

  const setCaptain = (playerId: number) => {
    setSelectedPlayers((prev) => {
      const next = new Map(prev);
      next.forEach((selection, id) => {
        next.set(id, { ...selection, is_captain: id === playerId });
      });
      return next;
    });
  };

  const setViceCaptain = (playerId: number) => {
    setSelectedPlayers((prev) => {
      const next = new Map(prev);
      next.forEach((selection, id) => {
        next.set(id, { ...selection, is_vice_captain: id === playerId });
      });
      return next;
    });
  };

  const selectedCount = selectedPlayers.size;
  const captainId = [...selectedPlayers.values()].find((p) => p.is_captain)?.player_id;
  const viceCaptainId = [...selectedPlayers.values()].find((p) => p.is_vice_captain)?.player_id;

  const groupedPlayers = useMemo(() => {
    const groups: Record<string, Player[]> = {};
    players.forEach((player) => {
      if (!groups[player.role]) groups[player.role] = [];
      groups[player.role].push(player);
    });

    Object.values(groups).forEach((group) => {
      group.sort((a, b) => {
        const pointsDiff = (b.total_points || 0) - (a.total_points || 0);
        if (pointsDiff !== 0) return pointsDiff;
        return a.name.localeCompare(b.name);
      });
    });

    return groups;
  }, [players]);

  const validateEdit = () => {
    if (selectedCount !== 11) return 'Select exactly 11 players.';
    if (!captainId) return 'Select a captain.';
    if (!viceCaptainId) return 'Select a vice captain.';
    if (captainId === viceCaptainId) return 'Captain and vice captain must be different.';

    for (const role of ROLE_ORDER) {
      const rolePlayers = groupedPlayers[role] || [];
      const count = rolePlayers.filter((player) => selectedPlayers.has(player.id)).length;
      if (count < 1) return `At least 1 ${role} is required.`;
    }

    return null;
  };

  const saveEdit = async () => {
    if (!editingTeam || !selectedMatchId) return;

    const error = validateEdit();
    if (error) {
      alert(error);
      return;
    }

    setSaving(true);
    try {
      const payload = {
        user_id: editingTeam.user_id,
        match_id: selectedMatchId,
        players: [...selectedPlayers.values()],
      };
      const res = await client.put('/api/admin/teams', payload);
      setTeams(res.data?.teams || []);
      closeEdit();
    } catch (err: any) {
      console.error('Failed to update team', err);
      alert(err?.response?.data?.detail || 'Failed to update team');
    } finally {
      setSaving(false);
    }
  };

  if (loadingMatches) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-indigo-600" />
      </div>
    );
  }

  return (
    <div className="space-y-6 text-slate-900">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Submitted Teams</h1>
          <p className="text-sm text-gray-500 mt-1">Review user teams match by match and edit when needed.</p>
        </div>
        <select
          value={selectedMatchId ?? ''}
          onChange={(e) => setSelectedMatchId(Number(e.target.value))}
          className="border border-gray-300 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
        >
          {matches.map((match) => (
            <option key={match.id} value={match.id}>
              Match {match.id}: {match.team1} vs {match.team2} ({match.team_count} teams)
            </option>
          ))}
        </select>
      </div>

      {/* Matches grid hidden: use dropdown above to select a match */}

      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5">
        {loadingTeams ? (
          <div className="flex items-center justify-center h-48">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600" />
          </div>
        ) : teams.length === 0 ? (
          <div className="text-center py-12 text-gray-400">No submitted teams for this match yet.</div>
        ) : (
          <div className="grid grid-cols-1 2xl:grid-cols-2 gap-5">
            {teams.map((team) => (
              <div key={team.user_id} className="rounded-2xl border border-gray-200 bg-gray-50 p-5">
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-4">
                  <div>
                    <h2 className="text-lg font-bold text-gray-900">{team.user_name}</h2>
                    <p className="text-sm text-gray-500">{team.user_email || 'No email'}</p>
                    <p className="text-xs text-gray-400 mt-1">{team.user_mobile || 'No mobile'}</p>
                  </div>
                  <button
                    onClick={() => openEdit(team)}
                    className="inline-flex items-center gap-2 bg-indigo-600 text-white px-3 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
                  >
                    Edit Team
                  </button>
                </div>

                <div className="flex flex-wrap gap-2 mb-4">
                  {Object.entries(team.team_counts).map(([teamCode, count]) => (
                    <span key={teamCode} className="text-xs font-semibold px-2.5 py-1 rounded-full bg-indigo-100 text-indigo-700">
                      {teamCode}: {count}
                    </span>
                  ))}
                  <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-amber-100 text-amber-700">
                    C: {team.captain_name || '-'}
                  </span>
                  <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-sky-100 text-sky-700">
                    VC: {team.vice_captain_name || '-'}
                  </span>
                </div>

                <div className="space-y-3">
                  {ROLE_ORDER.map((role) => {
                    const rolePlayers = team.players.filter((player) => player.role === role);
                    if (rolePlayers.length === 0) return null;

                    return (
                      <div key={role}>
                        <h3 className="text-xs font-bold uppercase tracking-wide text-gray-500 mb-2">{role}</h3>
                        <div className="flex flex-wrap gap-2">
                          {rolePlayers.map((player) => (
                            <span
                              key={player.player_id}
                              className="inline-flex items-center gap-2 rounded-full bg-white border border-gray-200 px-3 py-1.5 text-sm text-gray-700"
                            >
                              <span>{player.player_name}</span>
                              <span className="text-xs text-gray-400">{player.team}</span>
                              {player.is_captain && <span className="text-[10px] font-bold text-amber-600">C</span>}
                              {player.is_vice_captain && <span className="text-[10px] font-bold text-sky-600">VC</span>}
                            </span>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {editingTeam && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/50" onClick={closeEdit} />
          <div className="relative z-10 w-full max-w-5xl max-h-[90vh] overflow-y-auto rounded-2xl bg-white shadow-xl">
            <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
              <div>
                <h2 className="text-xl font-bold text-gray-900">Edit Team</h2>
                <p className="text-sm text-gray-500">{editingTeam.user_name} for Match {selectedMatchId}</p>
              </div>
              <button onClick={closeEdit} className="text-gray-400 hover:text-gray-700">
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="px-6 py-5 space-y-5">
              <div className="flex flex-wrap gap-3 text-sm">
                <span className="font-semibold text-indigo-700">{selectedCount}/11 selected</span>
                <span className="text-gray-500">Captain: {players.find((p) => p.id === captainId)?.name || '-'}</span>
                <span className="text-gray-500">Vice Captain: {players.find((p) => p.id === viceCaptainId)?.name || '-'}</span>
              </div>

              {ROLE_ORDER.map((role) => {
                const rolePlayers = groupedPlayers[role] || [];
                return (
                  <div key={role} className="rounded-2xl border border-gray-200 overflow-hidden">
                    <div className="bg-gray-50 px-4 py-3 text-sm font-semibold text-gray-700">{role}</div>
                    <div className="divide-y divide-gray-100">
                      {rolePlayers.map((player) => {
                        const isSelected = selectedPlayers.has(player.id);
                        const isCaptain = captainId === player.id;
                        const isViceCaptain = viceCaptainId === player.id;

                        return (
                          <div key={player.id} className={`px-4 py-3 flex items-center gap-3 ${isSelected ? 'bg-indigo-50' : 'bg-white'}`}>
                            <button
                              type="button"
                              onClick={() => togglePlayer(player.id)}
                              className={`w-5 h-5 rounded border-2 flex items-center justify-center ${isSelected ? 'bg-green-500 border-green-500 text-white' : 'border-gray-300'}`}
                            >
                              {isSelected && (
                                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                </svg>
                              )}
                            </button>
                            <div className="flex-1 min-w-0">
                              <div className="font-medium text-gray-900">{player.name}</div>
                              <div className="text-xs text-gray-500">
                                {player.team} • {(player.total_points || 0).toFixed(2)} pts
                              </div>
                            </div>
                            <button
                              type="button"
                              disabled={!isSelected}
                              onClick={() => setCaptain(player.id)}
                              className={`px-2.5 py-1 rounded-full text-xs font-bold border ${isCaptain ? 'bg-amber-500 text-white border-amber-500' : 'border-amber-300 text-amber-700 disabled:opacity-40'}`}
                            >
                              C
                            </button>
                            <button
                              type="button"
                              disabled={!isSelected}
                              onClick={() => setViceCaptain(player.id)}
                              className={`px-2.5 py-1 rounded-full text-xs font-bold border ${isViceCaptain ? 'bg-sky-500 text-white border-sky-500' : 'border-sky-300 text-sky-700 disabled:opacity-40'}`}
                            >
                              VC
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="sticky bottom-0 bg-white border-t border-gray-200 px-6 py-4 flex justify-end gap-3">
              <button
                onClick={closeEdit}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={saveEdit}
                disabled={saving}
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                {saving ? 'Saving...' : 'Save Team'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
