import { useState, useEffect, useRef, type FormEvent } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import client from '../api/client';
import type { Player, TeamSelection, TeamBackup, TossInfo } from '../types';
import { getTeamTheme } from '../utils/teamTheme';
import { useToast } from '../components/Toast';
import { PlayerListSkeleton } from '../components/Skeleton';

interface SelectedPlayer {
  player_id: number;
  is_captain: boolean;
  is_vice_captain: boolean;
}

interface PlayingXiState {
  announced: boolean;
  url: string | null;
  playingCount?: number;
  substituteCount?: number;
  lineupWindowOpen?: boolean;
  isTodayMatch?: boolean;
}

interface LastMatchXiTeam {
  match_id: number;
  team: string;
  player_ids: number[];
  impact_sub_player_ids?: number[];
}

interface PlayerHistoryToggleProps {
  player: Player;
  isOpen: boolean;
  isSelected: boolean;
  onToggle: () => void;
}

const LINEUPS_TAB = 'Lineups' as const;

const ROLE_CONFIG: Record<string, { label: string; color: string; bg: string; border: string }> = {
  Wicketkeeper: { label: 'WK', color: 'text-white/70', bg: 'bg-white/10', border: 'border-white/20' },
  Batter: { label: 'BAT', color: 'text-blue-300', bg: 'bg-blue-500/20', border: 'border-blue-500/30' },
  AllRounder: { label: 'AR', color: 'text-blue-300', bg: 'bg-blue-500/20', border: 'border-blue-500/30' },
  Bowler: { label: 'BOWL', color: 'text-blue-300', bg: 'bg-blue-500/20', border: 'border-blue-500/30' },
};

const REQUIRED_ROLES = ['Wicketkeeper', 'Batter', 'AllRounder', 'Bowler'] as const;
type SelectionTab = typeof LINEUPS_TAB | (typeof REQUIRED_ROLES)[number];

const formatRoleName = (role: string) => (role === 'AllRounder' ? 'All Rounder' : role);
const formatPoints = (value: number | null | undefined) => {
  if (value == null || Number.isNaN(value)) return '-';
  const rounded = Math.round(value * 2) / 2;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
};

/* Ground view player node */
function GroundPlayer({
  player,
  isCaptain,
  isVC,
  teamBadge,
  onTap,
}: {
  player: Player;
  isCaptain: boolean;
  isVC: boolean;
  teamBadge: React.ReactNode;
  onTap: () => void;
}) {
  return (
    <button type="button" onClick={onTap} className="flex flex-col items-center group">
      <div
        className={`w-9 h-9 rounded-full flex items-center justify-center text-[10px] font-bold shadow-lg transition-transform group-active:scale-90 ${
          isCaptain
            ? 'bg-amber-400 text-black ring-2 ring-amber-300'
            : isVC
            ? 'bg-sky-400 text-black ring-2 ring-sky-300'
            : 'bg-white text-blue-900'
        }`}
      >
        {isCaptain ? 'C' : isVC ? 'VC' : player.name.charAt(0)}
      </div>
      <p className="text-white text-[9px] font-medium mt-0.5 max-w-[56px] text-center truncate leading-tight">
        {player.name.split(' ').pop()}
      </p>
      <span className="mt-0.5">{teamBadge}</span>
    </button>
  );
}

/* Empty slot placeholder */
function EmptySlot({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center opacity-30">
      <div className="w-9 h-9 rounded-full border-2 border-dashed border-white/40 flex items-center justify-center">
        <svg className="w-4 h-4 text-white/40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
        </svg>
      </div>
      {label && <p className="text-white/30 text-[8px] mt-0.5">{label}</p>}
    </div>
  );
}

function PlayerHistoryToggle({ player, isOpen, isSelected, onToggle }: PlayerHistoryToggleProps) {
  const recentHistory = player.recent_history || [];

  return (
    <div className="relative z-40 flex-shrink-0 self-start">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onToggle();
        }}
        aria-label={`Toggle recent history for ${player.name}`}
        aria-expanded={isOpen}
        className={`flex h-7 w-7 items-center justify-center rounded-full border transition-all ${
          isOpen
            ? 'border-sky-300/80 bg-sky-400/45 text-sky-50 shadow-lg shadow-sky-400/20'
            : isSelected
            ? 'border-sky-300/70 bg-sky-400/30 text-sky-50 hover:border-sky-200/90 hover:bg-sky-400/40'
            : 'border-white/25 bg-white/15 text-white/80 hover:border-white/45 hover:bg-white/20'
        }`}
      >
        <svg className={`h-3.5 w-3.5 transition-transform ${isOpen ? 'rotate-180' : ''}`} viewBox="0 0 20 20" fill="currentColor">
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {isOpen && (
        <div
          className="mobile-safe-blur absolute left-0 top-full z-50 mt-2 w-48 overflow-hidden rounded-2xl border border-white/15 bg-[#04110b]/98 shadow-2xl shadow-black/60 backdrop-blur-md ring-1 ring-white/10"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="border-b border-white/10 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-300">Recent Form</div>
          </div>
          <div className="max-h-48 overflow-y-auto px-3 py-2">
            {recentHistory.length > 0 ? (
              recentHistory.map((entry) => (
                <div key={`${player.id}-${entry.match_id}`} className="flex items-center justify-between gap-3 border-b border-white/5 py-2 last:border-b-0">
                  <span className="text-xs text-white/65">
                    Match#{entry.match_id}{entry.opponent ? ` vs ${entry.opponent}` : ''}
                  </span>
                  <span className={`text-xs font-semibold ${entry.did_not_play ? 'text-white/40' : 'text-blue-300'}`}>
                    {entry.did_not_play ? 'DNP' : formatPoints(entry.points)}
                  </span>
                </div>
              ))
            ) : (
              <div className="py-3 text-xs text-white/40">No completed matches yet.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function SelectTeamPage() {
  const { matchId } = useParams<{ matchId: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();

  const [players, setPlayers] = useState<Player[]>([]);
  const [selected, setSelected] = useState<Map<number, SelectedPlayer>>(new Map());
  const [activeTab, setActiveTab] = useState<SelectionTab>(LINEUPS_TAB);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [playingXi, setPlayingXi] = useState<PlayingXiState>({ announced: false, url: null });
  const [tossInfo, setTossInfo] = useState<TossInfo | null>(null);
  const [matchTeams, setMatchTeams] = useState<string[]>([]);
  const [backups, setBackups] = useState<number[]>([]);
  const [backupDetails, setBackupDetails] = useState<TeamBackup[]>([]);
  const [showBackupPanel, setShowBackupPanel] = useState(false);
  const [showPlayerSearch, setShowPlayerSearch] = useState(false);
  const [playerSearch, setPlayerSearch] = useState('');
  const [openHistoryPlayerId, setOpenHistoryPlayerId] = useState<number | null>(null);
  const [lastMatchXi, setLastMatchXi] = useState<Record<string, LastMatchXiTeam>>({});
  const touchStartXRef = useRef<number | null>(null);
  const touchStartYRef = useRef<number | null>(null);
  const backupPanelRef = useRef<HTMLDivElement | null>(null);
  const refreshTimerRef = useRef<number | null>(null);
  const lineupWindowOpen = Boolean(playingXi.lineupWindowOpen);
  const showAvailabilityDetails = lineupWindowOpen;
  const isTodayMatch = Boolean(playingXi.isTodayMatch);

  const hasFullAvailabilityBreakdown =
    showAvailabilityDetails &&
    playingXi.announced &&
    (((playingXi.playingCount || 0) >= 22) ||
      ((playingXi.substituteCount || 0) >= 10) ||
      players.some(
        (player) =>
          player.availability_status === 'substitute' ||
          player.availability_status === 'unavailable',
      ));

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [playersRes, teamRes, backupsRes] = await Promise.all([
          client.get(`/api/players?match_id=${matchId}`),
          client.get(`/api/teams/my?match_id=${matchId}`).catch(() => ({ data: [] })),
          client.get(`/api/teams/my-backups?match_id=${matchId}`).catch(() => ({ data: [] })),
        ]);
        const data = playersRes.data || {};
        const groupedPlayers = data.players || data;
        const flat = Array.isArray(groupedPlayers)
          ? groupedPlayers
          : (Object.values(groupedPlayers).flat() as Player[]);
        setPlayers(flat);
        setMatchTeams(Array.isArray(data.match_teams) ? data.match_teams : []);
        setPlayingXi({
          announced: Boolean(data.playing_xi?.announced),
          url: data.playing_xi?.url || null,
          playingCount: data.playing_xi?.playing_count || 0,
          substituteCount: data.playing_xi?.substitute_count || 0,
          lineupWindowOpen: Boolean(data.lineup_window_open),
          isTodayMatch: Boolean(data.is_today_match),
        });
        setTossInfo(data.toss || null);
        setLastMatchXi(data.last_match_xi || {});

        const existing: TeamSelection[] = teamRes.data || [];
        if (existing.length > 0) {
          const map = new Map<number, SelectedPlayer>();
          existing.forEach((t) => {
            map.set(t.player_id, {
              player_id: t.player_id,
              is_captain: t.is_captain,
              is_vice_captain: t.is_vice_captain,
            });
          });
          setSelected(map);
        }
        const existingBackups: TeamBackup[] = (backupsRes as any).data || [];
        setBackupDetails(existingBackups);
        setBackups(existingBackups.map((entry) => entry.backup_player_id));
        if (existingBackups.length > 0) setShowBackupPanel(true);
      } catch {
        toast('Failed to load players.', 'error');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [matchId, toast]);

  useEffect(() => {
    if (refreshTimerRef.current) {
      window.clearInterval(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }

    if (!loading && showAvailabilityDetails && (!playingXi.announced || !hasFullAvailabilityBreakdown)) {
      refreshTimerRef.current = window.setInterval(() => {
        void (async () => {
          try {
            const res = await client.get(`/api/players?match_id=${matchId}`);
            const data = res.data || {};
            const groupedPlayers = data.players || data;
            const flat = Array.isArray(groupedPlayers)
              ? groupedPlayers
              : (Object.values(groupedPlayers).flat() as Player[]);
            setPlayers(flat);
            setMatchTeams(Array.isArray(data.match_teams) ? data.match_teams : []);
            setPlayingXi({
              announced: Boolean(data.playing_xi?.announced),
              url: data.playing_xi?.url || null,
              playingCount: data.playing_xi?.playing_count || 0,
              substituteCount: data.playing_xi?.substitute_count || 0,
              lineupWindowOpen: Boolean(data.lineup_window_open),
              isTodayMatch: Boolean(data.is_today_match),
            });
            setTossInfo(data.toss || null);
            setLastMatchXi(data.last_match_xi || {});
          } catch {
            // keep trying until the cache becomes ready
          }
        })();
      }, 15000);
    }

    return () => {
      if (refreshTimerRef.current) {
        window.clearInterval(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
    };
  }, [matchId, loading, showAvailabilityDetails, playingXi.announced, hasFullAvailabilityBreakdown]);

  useEffect(() => {
    if (!showBackupPanel) return;
    const timer = window.setTimeout(() => {
      backupPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 120);
    return () => window.clearTimeout(timer);
  }, [showBackupPanel]);

  useEffect(() => {
    setOpenHistoryPlayerId(null);
  }, [activeTab, showPlayerSearch]);

  useEffect(() => {
    if (!showAvailabilityDetails) {
      setShowPlayerSearch(false);
      setPlayerSearch('');
    }
  }, [showAvailabilityDetails]);

  const togglePlayer = (playerId: number) => {
    setOpenHistoryPlayerId((current) => (current === playerId ? null : current));
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(playerId)) {
        next.delete(playerId);
      } else {
        next.set(playerId, { player_id: playerId, is_captain: false, is_vice_captain: false });
      }
      return next;
    });
    setBackups((prev) => {
      const next = prev.filter((id) => id !== playerId);
      setBackupDetails(rebuildBackupDetails(next));
      return next;
    });
  };

  const setCaptain = (playerId: number) => {
    setSelected((prev) => {
      const next = new Map(prev);
      next.forEach((v, k) => {
        next.set(k, { ...v, is_captain: k === playerId, is_vice_captain: k === playerId ? false : v.is_vice_captain });
      });
      return next;
    });
  };

  const setViceCaptain = (playerId: number) => {
    setSelected((prev) => {
      const next = new Map(prev);
      next.forEach((v, k) => {
        next.set(k, { ...v, is_vice_captain: k === playerId, is_captain: k === playerId ? false : v.is_captain });
      });
      return next;
    });
  };

  const selectedCount = selected.size;
  const selectedIds = new Set(selected.keys());
  const playerById = new Map(players.map((player) => [player.id, player]));
  let captainId: number | undefined;
  let vcId: number | undefined;
  selected.forEach((entry) => {
    if (entry.is_captain) captainId = entry.player_id;
    if (entry.is_vice_captain) vcId = entry.player_id;
  });

  const rebuildBackupDetails = (ids: number[]) =>
    ids
      .slice(0, 3)
      .map((playerId, index) => {
        const existing = backupDetails.find((entry) => entry.backup_player_id === playerId);
        const player = playerById.get(playerId);
        return {
          backup_order: index + 1,
          backup_player_id: playerId,
          backup_player_name: existing?.backup_player_name || player?.name || `Player ${playerId}`,
          backup_team: existing?.backup_team || player?.team || '',
          backup_role: existing?.backup_role || player?.role || '',
          replaced_player_id: existing?.replaced_player_id ?? null,
          replaced_player_name: existing?.replaced_player_name ?? null,
        };
      });

  const selectedByTeam: Record<string, number> = {};
  const playersByRole = REQUIRED_ROLES.reduce<Record<string, Player[]>>((acc, role) => {
    acc[role] = [];
    return acc;
  }, {});
  const selectedPlayersByRole = REQUIRED_ROLES.reduce<Record<string, Player[]>>((acc, role) => {
    acc[role] = [];
    return acc;
  }, {});
  const selectedRoleCounts = REQUIRED_ROLES.reduce<Record<string, number>>((acc, role) => {
    acc[role] = 0;
    return acc;
  }, {});
  const selectedUnavailableCounts = REQUIRED_ROLES.reduce<Record<string, number>>((acc, role) => {
    acc[role] = 0;
    return acc;
  }, {});
  const selectedSubstituteCounts = REQUIRED_ROLES.reduce<Record<string, number>>((acc, role) => {
    acc[role] = 0;
    return acc;
  }, {});
  const lineupPlayersByTeam: Record<string, Record<string, Player[]>> = {};
  const preAnnouncementPlayersByTeam: Record<string, Player[]> = {};

  players.forEach((player) => {
    if (player.role in playersByRole) {
      playersByRole[player.role].push(player);
    }

    if (!preAnnouncementPlayersByTeam[player.team]) {
      preAnnouncementPlayersByTeam[player.team] = [];
    }
    preAnnouncementPlayersByTeam[player.team].push(player);

    if (!lineupPlayersByTeam[player.team]) {
      lineupPlayersByTeam[player.team] = { available: [], substitute: [], unavailable: [] };
    }
    const availabilityKey = player.availability_status;
    if (availabilityKey && availabilityKey in lineupPlayersByTeam[player.team]) {
      lineupPlayersByTeam[player.team][availabilityKey].push(player);
    }

    if (!selectedIds.has(player.id)) return;

    selectedByTeam[player.team] = (selectedByTeam[player.team] || 0) + 1;
    if (player.role in selectedPlayersByRole) {
      selectedPlayersByRole[player.role].push(player);
      selectedRoleCounts[player.role] += 1;
      if (player.availability_status === 'unavailable') selectedUnavailableCounts[player.role] += 1;
      if (player.availability_status === 'substitute') selectedSubstituteCounts[player.role] += 1;
    }
  });

  const teamsInMatch =
    matchTeams.length === 2 ? matchTeams : [...new Set(players.map((player) => player.team))].sort();

  const canSelectPlayer = (player: Player) => {
    if (selectedIds.has(player.id)) return true;
    if (selectedCount >= 11) return false;

    const simulatedCounts = { ...selectedRoleCounts };
    if (player.role in simulatedCounts) {
      simulatedCounts[player.role] += 1;
    }

    const remainingSlots = 11 - (selectedCount + 1);
    const missingRolesAfterSelection = REQUIRED_ROLES.filter((role) => simulatedCounts[role] === 0).length;
    return remainingSlots >= missingRolesAfterSelection;
  };

  const renderTeamBadge = (team: string, compact = false) => {
    const theme = getTeamTheme(team);
    return (
      <span
        className={`inline-flex items-center rounded-full border px-2 py-0.5 font-semibold ${compact ? 'text-[9px]' : 'text-[10px]'} ${theme.badgeClass}`}
      >
        {theme.label}
      </span>
    );
  };

  const validate = (): string | null => {
    if (selectedCount !== 11) return `Select exactly 11 players (currently ${selectedCount}).`;
    if (!captainId) return 'Select a Captain.';
    if (!vcId) return 'Select a Vice Captain.';
    if (captainId === vcId) return 'Captain and Vice Captain must be different players.';
    for (const role of REQUIRED_ROLES) {
      if (selectedRoleCounts[role] === 0) return `Select at least 1 ${ROLE_CONFIG[role]?.label || role}.`;
    }
    return null;
  };

  const closePlayerSearch = () => {
    setShowPlayerSearch(false);
    setPlayerSearch('');
  };

  const sortPlayersForDisplay = (list: Player[]) =>
    [...list].sort((a, b) => {
      const pointsDiff = (b.avg_points || 0) - (a.avg_points || 0);
      if (pointsDiff !== 0) return pointsDiff;
      return a.name.localeCompare(b.name);
    });

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();

    const validationError = validate();
    if (validationError) {
      toast(validationError, 'error');
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        match_id: Number(matchId),
        players: [...selected.values()],
        backups: backups.filter((playerId) => !selectedIds.has(playerId)).slice(0, 3),
      };
      await client.post('/api/teams', payload);
      toast('Team saved successfully!', 'success');
      setShowPreview(true);
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.response?.data?.error || 'Failed to save team.';
      toast(msg, 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const rolePlayers = REQUIRED_ROLES.reduce<Record<string, Player[]>>((acc, role) => {
    acc[role] = sortPlayersForDisplay(playersByRole[role]);
    return acc;
  }, {});

  const normalizedPlayerSearch = playerSearch.trim().toLowerCase();
  const playerSearchResults = normalizedPlayerSearch
    ? [...players]
        .filter((player) => {
          const haystack = [
            player.name,
            player.team,
            player.role,
            player.aliases || '',
          ]
            .join(' ')
            .toLowerCase();
          return haystack.includes(normalizedPlayerSearch);
        })
        .sort((a, b) => {
          const aStarts = a.name.toLowerCase().startsWith(normalizedPlayerSearch) ? 1 : 0;
          const bStarts = b.name.toLowerCase().startsWith(normalizedPlayerSearch) ? 1 : 0;
          if (aStarts !== bStarts) return bStarts - aStarts;
          const avgDiff = (b.avg_points || 0) - (a.avg_points || 0);
          if (avgDiff !== 0) return avgDiff;
          return a.name.localeCompare(b.name);
        })
    : [];

  const activeRole = activeTab === LINEUPS_TAB ? REQUIRED_ROLES[0] : activeTab;
  const selectionTabs = [
    { key: LINEUPS_TAB, label: 'XI' },
    ...REQUIRED_ROLES.map((role) => ({ key: role, label: ROLE_CONFIG[role].label })),
  ] as const;
  const tabKeys = selectionTabs.map((tab) => tab.key);

  const sortPlayersForLineupView = (list: Player[]) =>
    [...list].sort((a, b) => {
      const aOrder = a.availability_order ?? Number.MAX_SAFE_INTEGER;
      const bOrder = b.availability_order ?? Number.MAX_SAFE_INTEGER;
      if (aOrder !== bOrder) return aOrder - bOrder;
      const pointsDiff = (b.avg_points || 0) - (a.avg_points || 0);
      if (pointsDiff !== 0) return pointsDiff;
      return a.name.localeCompare(b.name);
    });

  const getLineupSectionPlayers = (team: string, status: Player['availability_status']) =>
    sortPlayersForLineupView(lineupPlayersByTeam[team]?.[status || ''] || []);

  const getLastMatchXiPlayers = (team: string) => {
    const preview = lastMatchXi[team];
    if (!preview?.player_ids?.length) return [];
    const order = new Map(preview.player_ids.map((playerId, index) => [playerId, index]));
    return [...(preAnnouncementPlayersByTeam[team] || [])]
      .filter((player) => order.has(player.id))
      .sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0));
  };

  const getLastMatchImpactSubPlayers = (team: string) => {
    const preview = lastMatchXi[team];
    if (!preview?.impact_sub_player_ids?.length) return [];
    const order = new Map(preview.impact_sub_player_ids.map((playerId, index) => [playerId, index]));
    return [...(preAnnouncementPlayersByTeam[team] || [])]
      .filter((player) => order.has(player.id))
      .sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0));
  };

  const getOtherPreviewPlayers = (team: string) => {
    const preview = lastMatchXi[team];
    const previewIds = new Set((preview?.player_ids || []).map((playerId) => Number(playerId)));
    const impactSubIds = new Set((preview?.impact_sub_player_ids || []).map((playerId) => Number(playerId)));
    return [...(preAnnouncementPlayersByTeam[team] || [])]
      .filter((player) => !previewIds.has(player.id) && !impactSubIds.has(player.id))
      .sort((a, b) => {
        const roleDiff =
          REQUIRED_ROLES.indexOf(a.role as (typeof REQUIRED_ROLES)[number]) -
          REQUIRED_ROLES.indexOf(b.role as (typeof REQUIRED_ROLES)[number]);
        if (roleDiff !== 0) return roleDiff;
        const pointsDiff = (b.total_points || 0) - (a.total_points || 0);
        if (pointsDiff !== 0) return pointsDiff;
        return a.name.localeCompare(b.name);
      });
  };

  const renderLineupPlayerCard = (
    player: Player,
    showAvailabilityBadge = false,
  ) => {
    const isSelected = selected.has(player.id);
    const isCaptain = captainId === player.id;
    const isVC = vcId === player.id;
    const selectionAllowed = canSelectPlayer(player);
    const availabilityStatus = player.availability_status || 'unavailable';

    return (
      <div
        key={player.id}
        onClick={() => {
          if (isSelected || selectionAllowed) togglePlayer(player.id);
        }}
        className={`cursor-pointer rounded-lg px-2 py-1.5 transition-all ${
          isSelected
            ? 'player-selected-highlight border border-sky-300/60'
            : !selectionAllowed
            ? 'cursor-not-allowed bg-white/[0.03] opacity-45'
            : 'bg-white/[0.04] hover:bg-white/[0.08]'
        }`}
      >
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="text-[11px] font-semibold leading-tight text-white whitespace-normal break-words">
              {player.name}
            </div>
            <div className="mt-0.5 flex items-center justify-between gap-2 text-[10px] text-white/50">
              <div className="flex items-center gap-2">
                <span>{ROLE_CONFIG[player.role]?.label || player.role}</span>
                <span className="font-semibold text-blue-300">
                  Avg {Math.round(player.avg_points || 0)}
                </span>
                {showAvailabilityBadge && showAvailabilityDetails && playingXi.announced && (
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-semibold ${
                      availabilityStatus === 'available'
                        ? 'border border-blue-400/25 bg-blue-500/10 text-blue-200'
                        : availabilityStatus === 'substitute'
                        ? 'border border-sky-400/25 bg-sky-500/10 text-sky-200'
                        : 'border border-red-400/20 bg-red-500/10 text-red-200'
                    }`}
                  >
                    <span
                      className={`h-2 w-2 rounded-full ${
                        availabilityStatus === 'available'
                          ? 'bg-blue-400'
                          : availabilityStatus === 'substitute'
                          ? 'bg-sky-400'
                          : 'bg-red-400'
                      }`}
                    />
                    {availabilityStatus === 'available' ? 'Avl' : availabilityStatus === 'substitute' ? 'Sub' : 'Unavl'}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (isSelected) setCaptain(player.id);
                  }}
                  disabled={!isSelected}
                  className={`h-6 w-6 rounded-full border text-[9px] font-bold ${
                    isCaptain
                      ? 'border-amber-400 bg-amber-500 text-white'
                      : isSelected
                      ? 'border-amber-400/40 text-amber-300'
                      : 'border-white/10 text-white/15'
                  }`}
                >
                  C
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (isSelected) setViceCaptain(player.id);
                  }}
                  disabled={!isSelected}
                  className={`h-6 w-6 rounded-full border text-[9px] font-bold ${
                    isVC
                      ? 'border-sky-400 bg-sky-500 text-white'
                      : isSelected
                      ? 'border-sky-400/40 text-sky-300'
                      : 'border-white/10 text-white/15'
                  }`}
                >
                  VC
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  };

  const getPreAnnouncementPlayers = (team: string) =>
    [...(preAnnouncementPlayersByTeam[team] || [])].sort((a, b) => {
      const roleDiff =
        REQUIRED_ROLES.indexOf(a.role as (typeof REQUIRED_ROLES)[number]) -
        REQUIRED_ROLES.indexOf(b.role as (typeof REQUIRED_ROLES)[number]);
      if (roleDiff !== 0) return roleDiff;
      const pointsDiff = (b.total_points || 0) - (a.total_points || 0);
      if (pointsDiff !== 0) return pointsDiff;
      return a.name.localeCompare(b.name);
    });

  const getBackupEligiblePlayers = (team: string) =>
    [...(preAnnouncementPlayersByTeam[team] || [])]
      .filter((player) => !selectedIds.has(player.id))
      .sort((a, b) => {
        const pointsDiff = (b.avg_points || 0) - (a.avg_points || 0);
        if (pointsDiff !== 0) return pointsDiff;
        return a.name.localeCompare(b.name);
      });

  const handleTabSwipeStart = (clientX: number, clientY: number) => {
    touchStartXRef.current = clientX;
    touchStartYRef.current = clientY;
  };

  const removeBackupAtIndex = (index: number) => {
    setBackups((prev) => {
      const next = prev.filter((_, currentIndex) => currentIndex !== index);
      setBackupDetails(rebuildBackupDetails(next));
      return next;
    });
  };

  const toggleBackupPlayer = (player: Player) => {
    if (selected.has(player.id)) return;

    const existingIndex = backups.indexOf(player.id);
    if (existingIndex >= 0) {
      removeBackupAtIndex(existingIndex);
      return;
    }

    if (backups.length >= 3) {
      toast('You can select at most 3 backup players.', 'error');
      return;
    }

    setBackups((prev) => {
      const next = [...prev, player.id];
      setBackupDetails(rebuildBackupDetails(next));
      return next;
    });
    setShowBackupPanel(true);
  };

  const handleTabSwipeEnd = (clientX: number, clientY: number) => {
    if (touchStartXRef.current == null || touchStartYRef.current == null) return;

    const deltaX = clientX - touchStartXRef.current;
    const deltaY = clientY - touchStartYRef.current;
    touchStartXRef.current = null;
    touchStartYRef.current = null;

    if (Math.abs(deltaX) < 45 || Math.abs(deltaX) < Math.abs(deltaY)) return;

    const currentIndex = tabKeys.indexOf(activeTab);
    if (currentIndex === -1) return;

    if (deltaX < 0 && currentIndex < tabKeys.length - 1) {
      setOpenHistoryPlayerId(null);
      setActiveTab(tabKeys[currentIndex + 1]);
    } else if (deltaX > 0 && currentIndex > 0) {
      setOpenHistoryPlayerId(null);
      setActiveTab(tabKeys[currentIndex - 1]);
    }
  };

  /* Ground view helpers */
  const getSelectedByRole = (role: string) => selectedPlayersByRole[role] || [];

  if (loading) {
    return (
      <div className="min-h-screen bg-black">
        <header className="sticky top-0 z-30 bg-black/90 border-b border-white/10 md:bg-black/80 md:backdrop-blur-lg">
          <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-white/10 animate-pulse" />
              <div className="space-y-1.5">
                <div className="h-5 w-36 rounded bg-white/10 animate-pulse" />
                <div className="h-3 w-20 rounded bg-white/10 animate-pulse" />
              </div>
            </div>
            <div className="h-8 w-14 rounded-xl bg-white/10 animate-pulse" />
          </div>
        </header>
        <div className="max-w-7xl mx-auto px-4 py-4">
          <PlayerListSkeleton />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black pb-24">
      {/* Sticky header */}
      <header className="sticky top-0 z-30 bg-black/90 border-b border-white/10 md:bg-black/80 md:backdrop-blur-lg">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link to="/dashboard" className="p-2 hover:bg-white/10 rounded-xl transition-all">
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </Link>
            <div>
              <h1 className="text-lg font-bold text-white">Select Your Team</h1>
              <p className="text-xs text-white/50">Match #{matchId}</p>
            </div>
          </div>
          <div
            className={`px-3 py-1.5 rounded-xl font-bold text-sm ${
              selectedCount === 11
                ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                : 'bg-white/10 text-white/70 border border-white/20'
            }`}
          >
            {selectedCount}/11{backups.length > 0 ? ` · B ${backups.length}/3` : ''}
          </div>
        </div>
      </header>

      {/* Two-column layout: player list left, ground right */}
      <div className="max-w-7xl mx-auto px-4 py-4 flex flex-col lg:flex-row gap-4">
        {/* LEFT — Player selection */}
        <div className="flex-1 min-w-0 space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3 text-xs text-white/50">
              {teamsInMatch.map((team) => (
                <div
                  key={team}
                  className={`inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-gradient-to-r ${getTeamTheme(team).tintClass} px-3 py-1.5 font-semibold text-white/80`}
                >
                  <span>{getTeamTheme(team).label}</span>
                  <span className="text-blue-300">{selectedByTeam[team] || 0}</span>
                </div>
              ))}
              <span className="flex items-center gap-1.5">
                <span className="w-5 h-5 bg-amber-500/30 border border-amber-500/50 rounded-full flex items-center justify-center text-[10px] font-bold text-amber-300">
                  C
                </span>
                2x
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-5 h-5 bg-sky-500/30 border border-sky-500/50 rounded-full flex items-center justify-center text-[10px] font-bold text-sky-300">
                  VC
                </span>
                1.5x
              </span>
            </div>
            {!showAvailabilityDetails && (
              <button
                type="button"
                onClick={() => setShowPlayerSearch(true)}
                className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/5 text-white/60 transition hover:bg-white/10 hover:text-white"
                aria-label="Search players"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="m21 21-4.35-4.35m1.85-5.15a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z" />
                </svg>
              </button>
            )}
          </div>

          {showPlayerSearch && !showAvailabilityDetails && (
            <div className="flex items-center gap-2 rounded-2xl border border-white/10 bg-white/[0.04] px-3 py-2">
              <svg className="h-4 w-4 flex-shrink-0 text-white/40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="m21 21-4.35-4.35m1.85-5.15a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z" />
              </svg>
              <input
                type="text"
                value={playerSearch}
                onChange={(e) => setPlayerSearch(e.target.value)}
                placeholder="Search players from both squads"
                autoFocus
                className="min-w-0 flex-1 bg-transparent text-sm text-white placeholder:text-white/30 focus:outline-none"
              />
              <button
                type="button"
                onClick={closePlayerSearch}
                className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/5 text-white/60 transition hover:bg-white/10 hover:text-white"
                aria-label="Close player search"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18 18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}

          {showPlayerSearch && !showAvailabilityDetails && normalizedPlayerSearch && (
            <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.04]">
              <div className="max-h-72 overflow-y-auto">
                {playerSearchResults.length > 0 ? (
                  playerSearchResults.map((player) => {
                    const isSelected = selected.has(player.id);
                    const isCaptain = captainId === player.id;
                    const isVC = vcId === player.id;
                    const selectionAllowed = canSelectPlayer(player);
                    return (
                      <button
                        key={player.id}
                        type="button"
                        onClick={() => {
                          if (isSelected || selectionAllowed) {
                            togglePlayer(player.id);
                            setActiveTab(player.role as SelectionTab);
                          }
                        }}
                        disabled={!isSelected && !selectionAllowed}
                        className={`flex w-full items-center gap-3 border-b border-white/5 px-4 py-3 text-left transition last:border-b-0 ${
                          isSelected
                            ? 'player-selected-highlight border border-sky-300/60'
                            : !selectionAllowed
                            ? 'cursor-not-allowed opacity-45'
                            : 'bg-white/[0.02] hover:bg-white/[0.05]'
                        }`}
                      >
                        <div className={`flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full ${isSelected ? 'bg-sky-400' : 'border border-white/15 bg-white/5'}`}>
                          {isSelected ? (
                            <svg className="h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                            </svg>
                          ) : (
                            <span className="text-[10px] font-bold text-white/35">{player.name.charAt(0)}</span>
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            {renderTeamBadge(player.team, true)}
                            <span className="truncate text-sm font-medium text-white">{player.name}</span>
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-white/45">
                            <span>{ROLE_CONFIG[player.role]?.label || player.role}</span>
                            <span className="font-semibold text-blue-300">Avg {formatPoints(player.avg_points || 0)}</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          {isCaptain && (
                            <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-amber-500 text-[10px] font-bold text-white">
                              C
                            </span>
                          )}
                          {isVC && (
                            <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-sky-500 text-[10px] font-bold text-white">
                              VC
                            </span>
                          )}
                        </div>
                      </button>
                    );
                  })
                ) : (
                  <div className="px-4 py-6 text-center text-sm text-white/35">No players found.</div>
                )}
              </div>
            </div>
          )}

          {tossInfo?.announced && tossInfo.text && (
            <div className="rounded-2xl border border-cyan-400/20 bg-cyan-500/10 px-4 py-2 text-center text-xs font-semibold text-cyan-300">
              {tossInfo.text}
            </div>
          )}

          {showAvailabilityDetails && (
            <div
              className={`rounded-2xl border px-4 py-3 text-sm ${
                playingXi.announced
                  ? 'bg-blue-500/10 border-blue-400/20 text-blue-100'
                  : 'bg-amber-500/10 border-amber-400/20 text-amber-100'
              }`}
            >
              <div className="font-semibold">
                {playingXi.announced ? 'Playing XI announced' : 'Playing XI not announced'}
              </div>
              {playingXi.url && (
                <a
                  href={playingXi.url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-flex text-xs font-semibold text-cyan-300 hover:text-cyan-200"
                >
                  Open lineup page
                </a>
              )}
            </div>
          )}

          {showAvailabilityDetails && playingXi.announced && (
            <div className="space-y-2">
              {showPlayerSearch ? (
                <div className="flex items-center gap-2 rounded-2xl border border-white/10 bg-white/[0.04] px-3 py-2">
                  <svg className="h-4 w-4 flex-shrink-0 text-white/40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="m21 21-4.35-4.35m1.85-5.15a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z" />
                  </svg>
                  <input
                    type="text"
                    value={playerSearch}
                    onChange={(e) => setPlayerSearch(e.target.value)}
                    placeholder="Search players from both squads"
                    autoFocus
                    className="min-w-0 flex-1 bg-transparent text-sm text-white placeholder:text-white/30 focus:outline-none"
                  />
                  <button
                    type="button"
                    onClick={closePlayerSearch}
                    className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/5 text-white/60 transition hover:bg-white/10 hover:text-white"
                    aria-label="Close player search"
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18 18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              ) : (
                <div className="flex items-center justify-between gap-3 text-xs text-white/50">
                  <div className="flex flex-wrap items-center gap-4">
                    <span className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-blue-400"></span>
                      Avl
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-sky-400"></span>
                      Sub
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-red-400"></span>
                      Unavl
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowPlayerSearch(true)}
                    className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/5 text-white/60 transition hover:bg-white/10 hover:text-white"
                    aria-label="Search players"
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="m21 21-4.35-4.35m1.85-5.15a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z" />
                    </svg>
                  </button>
                </div>
              )}

              {showPlayerSearch && normalizedPlayerSearch && (
                <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.04]">
                  <div className="max-h-72 overflow-y-auto">
                    {playerSearchResults.length > 0 ? (
                      playerSearchResults.map((player) => {
                        const isSelected = selected.has(player.id);
                        const isCaptain = captainId === player.id;
                        const isVC = vcId === player.id;
                        const selectionAllowed = canSelectPlayer(player);
                        const availabilityStatus = player.availability_status || 'unavailable';
                        return (
                          <button
                            key={player.id}
                            type="button"
                            onClick={() => {
                              if (isSelected || selectionAllowed) {
                                togglePlayer(player.id);
                                setActiveTab(player.role as SelectionTab);
                              }
                            }}
                            disabled={!isSelected && !selectionAllowed}
                            className={`flex w-full items-center gap-3 border-b border-white/5 px-4 py-3 text-left transition last:border-b-0 ${
                              isSelected
                                ? 'player-selected-highlight border border-sky-300/60'
                                : !selectionAllowed
                                ? 'cursor-not-allowed opacity-45'
                                : 'bg-white/[0.02] hover:bg-white/[0.05]'
                            }`}
                          >
                            <div
                              className={`flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full ${
                                isSelected
                                  ? availabilityStatus === 'available'
                                    ? 'bg-sky-400'
                                    : availabilityStatus === 'substitute'
                                    ? 'bg-sky-500'
                                    : 'bg-red-500'
                                  : 'border border-white/15 bg-white/5'
                              }`}
                            >
                              {isSelected ? (
                                <svg className="h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                </svg>
                              ) : (
                                <span className="text-[10px] font-bold text-white/35">{player.name.charAt(0)}</span>
                              )}
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                {renderTeamBadge(player.team, true)}
                                <span className="truncate text-sm font-medium text-white">{player.name}</span>
                              </div>
                              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-white/45">
                                <span>{ROLE_CONFIG[player.role]?.label || player.role}</span>
                                <span className="font-semibold text-blue-300">Avg {formatPoints(player.avg_points || 0)}</span>
                                {showAvailabilityDetails && playingXi.announced && (
                                  <span
                                    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-semibold ${
                                      availabilityStatus === 'available'
                                        ? 'border border-blue-400/25 bg-blue-500/10 text-blue-200'
                                        : availabilityStatus === 'substitute'
                                        ? 'border border-sky-400/25 bg-sky-500/10 text-sky-200'
                                        : 'border border-red-400/20 bg-red-500/10 text-red-200'
                                    }`}
                                  >
                                    <span
                                      className={`h-2 w-2 rounded-full ${
                                        availabilityStatus === 'available'
                                          ? 'bg-blue-400'
                                          : availabilityStatus === 'substitute'
                                          ? 'bg-sky-400'
                                          : 'bg-red-400'
                                      }`}
                                    ></span>
                                    {availabilityStatus === 'available' ? 'Avl' : availabilityStatus === 'substitute' ? 'Sub' : 'Unavl'}
                                  </span>
                                )}
                              </div>
                            </div>
                            <div className="flex items-center gap-1">
                              {isCaptain && (
                                <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-amber-500 text-[10px] font-bold text-white">
                                  C
                                </span>
                              )}
                              {isVC && (
                                <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-sky-500 text-[10px] font-bold text-white">
                                  VC
                                </span>
                              )}
                            </div>
                          </button>
                        );
                      })
                    ) : (
                      <div className="px-4 py-6 text-center text-sm text-white/35">No players found.</div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          <button
            type="button"
            onClick={() => setShowBackupPanel((prev) => !prev)}
            className={`flex w-full items-center justify-between gap-3 rounded-2xl border px-4 py-3 text-left transition ${
              showBackupPanel
                ? 'border-sky-400/25 bg-sky-500/[0.06]'
                : 'border-white/10 bg-white/[0.03] hover:bg-white/[0.05]'
            }`}
            aria-expanded={showBackupPanel}
          >
            <div className="min-w-0">
              <p className="text-sm font-semibold text-white">Optional Backup (upto 3)</p>
              <p className="text-xs text-white/45">
                {backups.length > 0 ? `${backups.length}/3 selected` : 'Collapsed'}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {backups.length > 0 && (
                <span className="rounded-full border border-sky-400/25 bg-sky-500/10 px-2.5 py-1 text-[11px] font-semibold text-sky-300">
                  {backups.length}/3
                </span>
              )}
              <span
                className={`inline-flex h-8 w-8 items-center justify-center rounded-full border text-white/60 transition ${
                  showBackupPanel
                    ? 'border-sky-400/30 bg-sky-500/10 rotate-180'
                    : 'border-white/10 bg-white/5'
                }`}
              >
                ▼
              </span>
            </div>
          </button>

          {/* Role Tabs */}
          <form onSubmit={handleSubmit}>
            <div
              onTouchStart={(e) => {
                const touch = e.changedTouches[0];
                if (touch) handleTabSwipeStart(touch.clientX, touch.clientY);
              }}
              onTouchEnd={(e) => {
                const touch = e.changedTouches[0];
                if (touch) handleTabSwipeEnd(touch.clientX, touch.clientY);
              }}
            >
            <div className="flex items-center gap-1 rounded-xl border border-white/10 bg-white/5 p-1">
              {selectionTabs.map(({ key, label }) => {
                const hasUnavailableSelected =
                  key !== LINEUPS_TAB && showAvailabilityDetails && playingXi.announced && selectedUnavailableCounts[key] > 0;
                const hasSubstituteSelected =
                  key !== LINEUPS_TAB && showAvailabilityDetails && playingXi.announced && selectedSubstituteCounts[key] > 0;
                const selectedTabCount =
                  key === LINEUPS_TAB
                    ? selectedCount
                    : rolePlayers[key].filter((player) => selected.has(player.id)).length;
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => {
                      setOpenHistoryPlayerId(null);
                      setActiveTab(key);
                    }}
                    className={`min-w-0 flex-1 rounded-lg px-2 py-2 text-xs sm:px-3 sm:text-sm font-medium transition-all ${
                      activeTab === key
                        ? hasUnavailableSelected
                          ? 'bg-red-500 text-white shadow-lg shadow-red-500/20'
                          : hasSubstituteSelected
                          ? 'bg-sky-500 text-white shadow-lg shadow-sky-500/20'
                          : 'bg-white text-black shadow-lg'
                        : hasUnavailableSelected
                        ? 'bg-red-500/10 text-red-200 hover:bg-red-500/15'
                        : hasSubstituteSelected
                        ? 'bg-sky-500/10 text-sky-200 hover:bg-sky-500/15'
                        : 'text-white/50 hover:bg-white/5 hover:text-white'
                    }`}
                  >
                    <span className="truncate">{label}</span>
                    <span
                      className={`ml-1 rounded-full px-1.5 py-0.5 text-[10px] ${
                        activeTab === key
                          ? hasUnavailableSelected || hasSubstituteSelected
                            ? 'bg-white/15 text-white'
                            : 'bg-black/10 text-black/70'
                          : hasUnavailableSelected
                          ? 'bg-red-500/20 text-red-100'
                          : hasSubstituteSelected
                          ? 'bg-sky-500/20 text-sky-100'
                          : 'bg-white/10 text-white/60'
                      }`}
                    >
                      {selectedTabCount}
                    </span>
                  </button>
                );
              })}
            </div>

            {activeTab === LINEUPS_TAB ? (
              <div className="mt-4 space-y-2">
                <div className="grid grid-cols-2 gap-3">
                  {teamsInMatch.map((team) => {
                    const hasPreview = isTodayMatch && !playingXi.announced && Boolean(lastMatchXi[team]?.player_ids?.length);
                    return (
                      <div
                        key={team}
                        className={`overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-b ${getTeamTheme(team).tintClass} bg-white/5`}
                      >
                        <div className="border-b border-white/10 px-3 py-3">
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-xs font-bold text-white">{team}</div>
                            <div className="text-[11px] text-white/45">{selectedByTeam[team] || 0} selected</div>
                          </div>
                        </div>
                        {showAvailabilityDetails && playingXi.announced ? (
                          [
                            { key: 'available', label: 'Playing XI', accent: 'text-blue-300' },
                            { key: 'substitute', label: 'Substitutes', accent: 'text-sky-300' },
                            { key: 'unavailable', label: 'Unavailable', accent: 'text-red-300' },
                          ].map((section) => {
                            const sectionPlayers = getLineupSectionPlayers(team, section.key as Player['availability_status']);
                            return (
                              <div key={section.key} className="border-t border-white/10 px-2.5 py-2">
                                <div className={`mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] ${section.accent}`}>
                                  {section.label}
                                </div>
                                <div className="space-y-1">
                                  {sectionPlayers.length > 0 ? (
                                    sectionPlayers.map((player) => renderLineupPlayerCard(player))
                                  ) : (
                                    <div className="rounded-lg border border-dashed border-white/10 px-2 py-2 text-center text-[10px] text-white/30">
                                      No players
                                    </div>
                                  )}
                                </div>
                              </div>
                            );
                          })
                        ) : hasPreview ? (
                          [
                            { key: 'last', label: 'Last Match XI', accent: 'text-blue-300', players: getLastMatchXiPlayers(team) },
                            { key: 'impact', label: 'Impact Sub', accent: 'text-amber-300', players: getLastMatchImpactSubPlayers(team) },
                            { key: 'others', label: 'Others', accent: 'text-white/55', players: getOtherPreviewPlayers(team) },
                          ].map((section) => {
                            if (section.key === 'impact' && section.players.length === 0) return null;
                            return (
                              <div key={section.key} className="border-t border-white/10 px-2.5 py-2">
                                <div className={`mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] ${section.accent}`}>
                                  {section.label}
                                </div>
                                <div className="space-y-1">
                                  {section.players.length > 0 ? (
                                    section.players.map((player) => renderLineupPlayerCard(player))
                                  ) : (
                                    <div className="rounded-lg border border-dashed border-white/10 px-2 py-2 text-center text-[10px] text-white/30">
                                      No players
                                    </div>
                                  )}
                                </div>
                              </div>
                            );
                          })
                        ) : (
                          <div className="border-t border-white/10 px-2.5 py-2">
                            <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/55">
                              Squads
                            </div>
                            <div className="space-y-1">
                              {getPreAnnouncementPlayers(team).map((player) => renderLineupPlayerCard(player))}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="mt-4 overflow-visible rounded-2xl border border-white/10 bg-white/5">
              <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
                <div className="flex items-center gap-2">
                  <span
                    className={`px-2 py-0.5 text-xs font-bold rounded-lg ${ROLE_CONFIG[activeRole].bg} ${ROLE_CONFIG[activeRole].color} ${ROLE_CONFIG[activeRole].border} border`}
                  >
                    {formatRoleName(activeRole)}
                  </span>
                  <span className="text-white/40 text-xs">
                    ({rolePlayers[activeRole].filter((player) => selected.has(player.id)).length} selected)
                  </span>
                </div>
                {showAvailabilityDetails && playingXi.announced && selectedUnavailableCounts[activeRole] > 0 && (
                  <span className="rounded-full border border-red-500/25 bg-red-500/15 px-2 py-1 text-[10px] font-semibold text-red-200">
                    {selectedUnavailableCounts[activeRole]} unavailable selected
                  </span>
                )}
              </div>
              <div className="border-t border-white/5">
                {rolePlayers[activeRole].map((player) => {
                  const isSelected = selected.has(player.id);
                  const isCaptain = captainId === player.id;
                  const isVC = vcId === player.id;
                  const availabilityStatus = player.availability_status || 'unavailable';
                  const selectionAllowed = canSelectPlayer(player);

                  return (
                    <div
                      key={player.id}
                        onClick={() => {
                          setOpenHistoryPlayerId(null);
                          if (isSelected || selectionAllowed) togglePlayer(player.id);
                        }}
                        className={`flex items-start gap-3 px-4 py-3 border-b border-white/5 last:border-b-0 transition-all cursor-pointer select-none ${
                          isSelected
                            ? 'player-selected-highlight border border-sky-300/60'
                            : !selectionAllowed
                            ? 'opacity-45 cursor-not-allowed'
                            : 'bg-white/[0.02] hover:bg-white/[0.05]'
                        }`}
                      >
                        <PlayerHistoryToggle
                          player={player}
                          isOpen={openHistoryPlayerId === player.id}
                          isSelected={isSelected}
                          onToggle={() => {
                            setOpenHistoryPlayerId((current) => (current === player.id ? null : player.id));
                          }}
                        />

                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          {renderTeamBadge(player.team)}
                          <p className="min-w-0 truncate text-sm font-medium text-white">{player.name}</p>
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                          <span className="font-semibold text-blue-400">
                            Tot <span className="font-bold">{formatPoints(player.total_points || 0)}</span>
                          </span>
                          {(player.matches_played ?? 0) > 0 && (
                            <>
                              <span className="text-blue-300" title="Average points per match">
                                Avg {formatPoints(player.avg_points || 0)}
                              </span>
                              <span className="text-blue-300" title="Last match points">
                                Last {formatPoints(player.last_match_points)}
                              </span>
                              <span className="text-white/25" title="Matches played">
                                {player.matches_played}M
                              </span>
                            </>
                          )}
                          {showAvailabilityDetails && playingXi.announced && availabilityStatus === 'available' && (
                            <span className="inline-flex items-center gap-1 rounded-full border border-blue-400/30 bg-blue-500/15 px-2 py-0.5 font-semibold text-blue-200">
                              <span className="h-2 w-2 rounded-full bg-blue-400"></span>
                              Avl
                            </span>
                          )}
                          {showAvailabilityDetails && playingXi.announced && availabilityStatus === 'substitute' && (
                            <span className="inline-flex items-center gap-1 rounded-full border border-sky-400/30 bg-sky-500/15 px-2 py-0.5 font-semibold text-sky-200">
                              <span className="h-2 w-2 rounded-full bg-sky-400"></span>
                              Sub
                            </span>
                          )}
                          {showAvailabilityDetails && playingXi.announced && availabilityStatus === 'unavailable' && (
                            <span className="inline-flex items-center gap-1 rounded-full border border-red-400/25 bg-red-500/10 px-2 py-0.5 font-semibold text-red-200">
                              <span className="h-2 w-2 rounded-full bg-red-400"></span>
                              Unavl
                            </span>
                          )}
                        </div>
                      </div>

                      {/* C / VC buttons */}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (isSelected) setCaptain(player.id);
                        }}
                        disabled={!isSelected}
                        className={`flex-shrink-0 w-7 h-7 rounded-full border-2 flex items-center justify-center text-[10px] font-bold transition-all ${
                          isCaptain
                            ? 'bg-amber-500 border-amber-500 text-white'
                            : isSelected
                            ? 'border-amber-500/50 text-amber-400/50 hover:border-amber-500 hover:text-amber-400'
                            : 'border-white/10 text-white/10 cursor-not-allowed'
                        }`}
                      >
                        C
                      </button>

                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (isSelected) setViceCaptain(player.id);
                        }}
                        disabled={!isSelected}
                        className={`flex-shrink-0 w-7 h-7 rounded-full border-2 flex items-center justify-center text-[10px] font-bold transition-all ${
                          isVC
                            ? 'bg-sky-500 border-sky-500 text-white'
                            : isSelected
                            ? 'border-sky-500/50 text-sky-400/50 hover:border-sky-500 hover:text-sky-400'
                            : 'border-white/10 text-white/10 cursor-not-allowed'
                        }`}
                      >
                        VC
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
            )}

            {(showBackupPanel || backups.length > 0) && (
              <div ref={backupPanelRef} className="mt-4 rounded-2xl border border-sky-400/15 bg-sky-500/[0.04] p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-white">Backup Order</p>
                    <p className="text-xs text-white/45">
                      Used in order only if your XI has unavailable or substitute players at cutoff.
                    </p>
                  </div>
                  <span className="rounded-full border border-sky-400/20 bg-sky-500/10 px-2.5 py-1 text-[11px] font-semibold text-sky-300">
                    {backups.length}/3
                  </span>
                </div>

                <div className="mt-3 grid grid-cols-3 gap-2">
                  {[0, 1, 2].map((index) => {
                    const entry = backupDetails.find((detail) => detail.backup_order === index + 1);
                    return (
                      <button
                        key={index}
                        type="button"
                        onClick={() => {
                          if (entry) removeBackupAtIndex(index);
                        }}
                        className={`rounded-xl border px-3 py-3 text-left transition ${
                          entry
                            ? 'border-sky-400/20 bg-sky-500/10 hover:bg-sky-500/15'
                            : 'border-white/10 bg-white/[0.03]'
                        }`}
                      >
                        <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-sky-300">
                          Backup {index + 1}
                        </div>
                        <div className="mt-1 text-xs font-medium text-white">
                          {entry ? entry.backup_player_name : 'Empty'}
                        </div>
                        {entry && (
                          <div className="mt-1 text-[10px] text-white/45">
                            {getTeamTheme(entry.backup_team).label} · {ROLE_CONFIG[entry.backup_role]?.label || entry.backup_role}
                          </div>
                        )}
                      </button>
                    );
                  })}
                </div>

                <div className="mt-4 grid grid-cols-2 gap-3">
                  {teamsInMatch.map((team) => (
                    <div key={`backup-${team}`} className={`rounded-2xl border border-white/10 bg-gradient-to-b ${getTeamTheme(team).tintClass} bg-white/[0.03]`}>
                      <div className="flex items-center justify-between border-b border-white/10 px-3 py-3">
                        <div className="text-xs font-bold text-white">{team}</div>
                        <div className="text-[11px] text-white/45">
                          {backups.filter((playerId) => playerById.get(playerId)?.team === team).length} backup
                        </div>
                      </div>
                      <div className="max-h-[22rem] space-y-1 overflow-y-auto px-2.5 py-2">
                        {getBackupEligiblePlayers(team).map((player) => {
                          const backupIndex = backups.indexOf(player.id);
                          const isBackup = backupIndex >= 0;
                          return (
                            <button
                              key={`backup-player-${player.id}`}
                              type="button"
                              onClick={() => toggleBackupPlayer(player)}
                              className={`flex w-full items-start justify-between gap-2 rounded-lg px-2 py-2 text-left transition ${
                                isBackup ? 'bg-sky-500/12 ring-1 ring-sky-300/25' : 'bg-white/[0.04] hover:bg-white/[0.08]'
                              }`}
                            >
                              <div className="min-w-0 flex-1">
                                <div className="text-[11px] font-semibold leading-tight text-white whitespace-normal break-words">
                                  {player.name}
                                </div>
                                <div className="mt-0.5 flex items-center gap-2 text-[10px] text-white/50">
                                  <span>{ROLE_CONFIG[player.role]?.label || player.role}</span>
                                  <span className="font-semibold text-blue-300">
                                    Avg {Math.round(player.avg_points || 0)}
                                  </span>
                                </div>
                              </div>
                              {isBackup && (
                                <span className="rounded-full border border-sky-400/30 bg-sky-500/15 px-2 py-0.5 text-[10px] font-bold text-sky-300">
                                  #{backupIndex + 1}
                                </span>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            </div>
          </form>
        </div>

        {/* RIGHT — Live Ground View (sticky on desktop) */}
        <div className="lg:w-[340px] flex-shrink-0">
          <div className="lg:sticky lg:top-[73px]">
            <div
              className="rounded-2xl overflow-hidden shadow-lg md:shadow-xl"
              style={{
                background: 'linear-gradient(180deg, #1a5e1a 0%, #2d8a2d 30%, #3da33d 50%, #2d8a2d 70%, #1a5e1a 100%)',
              }}
            >
              <div className="text-center pt-3 pb-1">
                <p className="text-white/50 text-[10px] font-medium uppercase tracking-wider">Your XI</p>
                <p className={`text-sm font-bold ${selectedCount === 11 ? 'text-blue-300' : 'text-white/70'}`}>
                  {selectedCount}/11 Selected
                </p>
              </div>

              <div className="relative px-3 py-3">
                {/* Oval border */}
                <div className="absolute inset-x-6 inset-y-2 border-2 border-white/15 rounded-[50%]" />

                {/* Wicketkeeper */}
                <div className="relative z-10 mb-3">
                  <p className="text-center text-white/40 text-[9px] uppercase tracking-widest mb-1.5">WK</p>
                  <div className="flex justify-center gap-2.5 flex-wrap min-h-[52px] items-start">
                    {getSelectedByRole('Wicketkeeper').map((p) => (
                      <GroundPlayer
                        key={p.id}
                        player={p}
                        isCaptain={captainId === p.id}
                        isVC={vcId === p.id}
                        teamBadge={renderTeamBadge(p.team, true)}
                        onTap={() => togglePlayer(p.id)}
                      />
                    ))}
                    {getSelectedByRole('Wicketkeeper').length === 0 && <EmptySlot label="WK" />}
                  </div>
                </div>

                {/* Batters */}
                <div className="relative z-10 mb-3">
                  <p className="text-center text-white/40 text-[9px] uppercase tracking-widest mb-1.5">BAT</p>
                  <div className="flex justify-center gap-2.5 flex-wrap min-h-[52px] items-start">
                    {getSelectedByRole('Batter').map((p) => (
                      <GroundPlayer
                        key={p.id}
                        player={p}
                        isCaptain={captainId === p.id}
                        isVC={vcId === p.id}
                        teamBadge={renderTeamBadge(p.team, true)}
                        onTap={() => togglePlayer(p.id)}
                      />
                    ))}
                    {getSelectedByRole('Batter').length === 0 && <EmptySlot label="BAT" />}
                  </div>
                </div>

                {/* All-Rounders */}
                <div className="relative z-10 mb-3">
                  <p className="text-center text-white/40 text-[9px] uppercase tracking-widest mb-1.5">AR</p>
                  <div className="flex justify-center gap-2.5 flex-wrap min-h-[52px] items-start">
                    {getSelectedByRole('AllRounder').map((p) => (
                      <GroundPlayer
                        key={p.id}
                        player={p}
                        isCaptain={captainId === p.id}
                        isVC={vcId === p.id}
                        teamBadge={renderTeamBadge(p.team, true)}
                        onTap={() => togglePlayer(p.id)}
                      />
                    ))}
                    {getSelectedByRole('AllRounder').length === 0 && <EmptySlot label="AR" />}
                  </div>
                </div>

                {/* Bowlers */}
                <div className="relative z-10">
                  <p className="text-center text-white/40 text-[9px] uppercase tracking-widest mb-1.5">BOWL</p>
                  <div className="flex justify-center gap-2.5 flex-wrap min-h-[52px] items-start">
                    {getSelectedByRole('Bowler').map((p) => (
                      <GroundPlayer
                        key={p.id}
                        player={p}
                        isCaptain={captainId === p.id}
                        isVC={vcId === p.id}
                        teamBadge={renderTeamBadge(p.team, true)}
                        onTap={() => togglePlayer(p.id)}
                      />
                    ))}
                    {getSelectedByRole('Bowler').length === 0 && <EmptySlot label="BOWL" />}
                  </div>
                </div>
              </div>

              {/* Ground footer legend */}
              <div className="flex justify-center gap-3 pb-3 text-[10px] text-white/50">
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full bg-amber-400" /> C
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full bg-sky-400" /> VC
                </span>
                <span className="text-white/30">Tap to remove</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Sticky submit bar */}
      <div className="fixed bottom-0 left-0 right-0 z-30 bg-black/95 border-t border-white/10 md:bg-black/90 md:backdrop-blur-lg">
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-center justify-between gap-4">
          <div className="text-sm min-w-0">
            <span className={`font-bold ${selectedCount === 11 ? 'text-blue-400' : 'text-white/70'}`}>
              {selectedCount}/11
            </span>
            <span className="text-white/50 ml-2">
              {backups.length > 0 ? `B ${backups.length}/3 • ` : ''}
              {captainId ? 'C' : ''}
              {captainId && vcId ? ' / ' : ''}
              {vcId ? 'VC' : ''}
              {!captainId && !vcId && 'No C/VC'}
            </span>
          </div>
          <button
            onClick={(e) => {
              e.preventDefault();
              const form = document.querySelector('form');
              form?.requestSubmit();
            }}
            disabled={submitting}
            className="px-6 py-2.5 bg-blue-500 hover:bg-blue-600 text-white font-semibold rounded-xl shadow-lg shadow-blue-500/30 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? (
              <span className="inline-flex items-center gap-2">
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Saving...
              </span>
            ) : (
              'Save Team'
            )}
          </button>
        </div>
      </div>

      {/* Team Preview Modal — after save */}
      {showPreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 md:bg-black/70 md:backdrop-blur-sm">
          <div className="w-full max-w-md relative">
            <div
              className="rounded-3xl overflow-hidden shadow-2xl"
              style={{
                background: 'linear-gradient(180deg, #1a5e1a 0%, #2d8a2d 30%, #3da33d 50%, #2d8a2d 70%, #1a5e1a 100%)',
              }}
            >
              <div className="text-center pt-4 pb-2">
                <p className="text-white/60 text-xs font-medium uppercase tracking-wider">Your Team</p>
                <p className="text-white text-lg font-bold">Fantasy Cricket</p>
              </div>

              <div className="relative px-4 pb-6">
                <div className="absolute inset-x-8 inset-y-4 border-2 border-white/15 rounded-[50%]" />

                {REQUIRED_ROLES.map((role) => (
                  <div key={role} className="relative z-10 mb-4 last:mb-0">
                    <p className="text-center text-white/40 text-[10px] uppercase tracking-widest mb-2">
                      {ROLE_CONFIG[role].label}
                    </p>
                    <div className="flex justify-center gap-3 flex-wrap">
                      {getSelectedByRole(role).map((p) => (
                        <div key={p.id} className="flex flex-col items-center">
                          <div
                            className={`w-10 h-10 rounded-full flex items-center justify-center text-xs font-bold shadow-lg ${
                              captainId === p.id
                                ? 'bg-amber-400 text-black ring-2 ring-amber-300'
                                : vcId === p.id
                                ? 'bg-sky-400 text-black ring-2 ring-sky-300'
                                : 'bg-white text-blue-900'
                            }`}
                          >
                            {captainId === p.id ? 'C' : vcId === p.id ? 'VC' : p.name.charAt(0)}
                          </div>
                          <p className="text-white text-[10px] font-medium mt-1 max-w-[60px] text-center truncate">
                            {p.name.split(' ').pop()}
                          </p>
                          <span className="mt-1">{renderTeamBadge(p.team, true)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>

                <div className="flex justify-center gap-4 pb-4 text-[10px] text-white/50">
                  <span className="flex items-center gap-1">
                    <span className="w-3 h-3 rounded-full bg-amber-400"></span> C 2x
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-3 h-3 rounded-full bg-sky-400"></span> VC 1.5x
                  </span>
                </div>
            </div>

            <button
              onClick={() => {
                setShowPreview(false);
                navigate('/dashboard');
              }}
              className="mt-4 w-full py-3 bg-white text-black hover:bg-white/90 font-semibold rounded-xl shadow-lg transition-all"
            >
              Go to Dashboard
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
