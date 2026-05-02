import { useEffect, useState } from 'react';
import client from '../../api/client';
import type { Match } from '../../types';

interface Player {
	id: number;
	name: string;
	team: string;
	role: string;
}

interface UserInfo {
	id: number;
	name: string;
	email: string;
}

const statusBadge = (status: string) => {
	switch (status) {
		case 'live':
			return (
				<span className="inline-flex items-center gap-1 bg-green-100 text-green-700 text-xs font-semibold px-2.5 py-1 rounded-full">
					<span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
					Live
				</span>
			);
		case 'completed':
			return (
				<span className="inline-block bg-gray-100 text-gray-600 text-xs font-semibold px-2.5 py-1 rounded-full">
					Completed
				</span>
			);
		case 'nr':
			return (
				<span className="inline-block bg-rose-100 text-rose-700 text-xs font-semibold px-2.5 py-1 rounded-full">
					No Result
				</span>
			);
		default:
			return (
				<span className="inline-block bg-blue-100 text-blue-700 text-xs font-semibold px-2.5 py-1 rounded-full">
					Upcoming
				</span>
			);
	}
};

export default function ScoreControl() {
	const [matches, setMatches] = useState<Match[]>([]);
	const [loading, setLoading] = useState(true);
	const [recalculating, setRecalculating] = useState<Record<number, boolean>>({});
	const [validating, setValidating] = useState<Record<number, boolean>>({});
	const [validateResult, setValidateResult] = useState<Record<number, any>>({});
	const [recalcAllLoading, setRecalcAllLoading] = useState(false);
	const [toasts, setToasts] = useState<{ id: number; type: 'success' | 'error'; message: string }[]>([]);

	// Admin team submit state
	const [users, setUsers] = useState<UserInfo[]>([]);
	const [players, setPlayers] = useState<Player[]>([]);
	const [selectedUserId, setSelectedUserId] = useState<number | ''>('');
	const [selectedMatchId, setSelectedMatchId] = useState<number | ''>('');
	const [matchFilter, setMatchFilter] = useState<number | ''>('');
	const [selectedPlayers, setSelectedPlayers] = useState<Set<number>>(new Set());
	const [captainId, setCaptainId] = useState<number | null>(null);
	const [viceCaptainId, setViceCaptainId] = useState<number | null>(null);
	const [submitTeamLoading, setSubmitTeamLoading] = useState(false);

	let toastId = 0;

	const addToast = (type: 'success' | 'error', message: string) => {
		const id = ++toastId;
		setToasts((prev) => [...prev, { id, type, message }]);
		setTimeout(() => {
			setToasts((prev) => prev.filter((t) => t.id !== id));
		}, 4000);
	};

	const fetchMatches = async () => {
		try {
			const res = await client.get('/api/admin/matches');
			setMatches(res.data);
		} catch (err) {
			console.error('Failed to fetch matches', err);
		} finally {
			setLoading(false);
		}
	};

	useEffect(() => {
		fetchMatches();
		client.get('/api/admin/users').then((res) => setUsers(res.data)).catch(() => {});
		client.get('/api/admin/players').then((res) => setPlayers(res.data)).catch(() => {});
	}, []);

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

	const handleSubmitTeam = async () => {
		if (!selectedUserId || !selectedMatchId) return;
		if (selectedPlayers.size !== 11) return;
		if (!captainId || !viceCaptainId) return;
		if (captainId === viceCaptainId) return;

		setSubmitTeamLoading(true);
		try {
			await client.post('/api/admin/teams/submit', {
				user_id: selectedUserId,
				match_id: selectedMatchId,
				players: Array.from(selectedPlayers).map((pid) => ({
					player_id: pid,
					is_captain: pid === captainId,
					is_vice_captain: pid === viceCaptainId,
				})),
			});
			addToast('success', 'Team submitted successfully.');
			setSelectedPlayers(new Set());
			setCaptainId(null);
			setViceCaptainId(null);
		} catch (err) {
			console.error(err);
			addToast('error', 'Failed to submit team.');
		} finally {
			setSubmitTeamLoading(false);
		}
	};

	const recalculate = async (matchId: number) => {
		setRecalculating((prev) => ({ ...prev, [matchId]: true }));
		try {
			await client.post(`/api/admin/recalculate/${matchId}`);
			addToast('success', `Match #${matchId} scores recalculated successfully.`);
		} catch (err) {
			console.error('Recalculation failed', err);
			addToast('error', `Failed to recalculate match #${matchId}.`);
		} finally {
			setRecalculating((prev) => ({ ...prev, [matchId]: false }));
		}
	};

	const recalculateAll = async () => {
		setRecalcAllLoading(true);
		try {
			const eligibleMatches = matches.filter((m) => m.status === 'live' || m.status === 'completed');
			await Promise.all(eligibleMatches.map((m) => client.post(`/api/admin/recalculate/${m.id}`)));
			addToast('success', 'All live/completed matches recalculated successfully.');
		} catch (err) {
			console.error('Recalculate all failed', err);
			addToast('error', 'Failed to recalculate some matches.');
		} finally {
			setRecalcAllLoading(false);
		}
	};

	const validateCompute = async (matchId: number) => {
		setValidating((prev) => ({ ...prev, [matchId]: true }));
		setValidateResult((prev) => ({ ...prev, [matchId]: null }));
		try {
			const res = await client.post(`/api/admin/validate-compute/${matchId}`);
			setValidateResult((prev) => ({ ...prev, [matchId]: res.data }));
			if (res.data.safe_to_recompute) {
				addToast('success', `Match #${matchId}: Safe to recompute (no data loss detected)`);
			} else {
				addToast('error', `Match #${matchId}: NOT safe — computed total (${res.data.computed_total}) < stored (${res.data.stored_total}). Dot balls likely missing.`);
			}
		} catch (err) {
			console.error('Validate failed', err);
			addToast('error', `Failed to validate match #${matchId}.`);
		} finally {
			setValidating((prev) => ({ ...prev, [matchId]: false }));
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
		<div>
			{/* Toast container */}
			<div className="fixed top-4 right-4 z-50 flex flex-col gap-2">
				{toasts.map((toast) => (
					<div
						key={toast.id}
						className={`px-4 py-3 rounded-lg shadow-lg text-sm font-medium text-white transition-all ${
							toast.type === 'success' ? 'bg-green-600' : 'bg-red-600'
						}`}
					>
						{toast.message}
					</div>
				))}
			</div>

			<div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
				<div className="flex items-center gap-4 w-full sm:w-auto">
					<h1 className="text-2xl font-bold text-gray-800">Score Control</h1>
					<div className="hidden sm:block">
						<label className="text-xs text-gray-500 mr-2">Filter:</label>
						<select
							value={matchFilter}
							onChange={(e) => setMatchFilter(e.target.value ? Number(e.target.value) : '')}
							className="border border-gray-300 rounded px-2 py-1 text-sm"
						>
							<option value="">All matches</option>
							{matches.map((m) => (
								<option key={m.id} value={m.id}>#{m.id} {m.team1} vs {m.team2}</option>
							))}
						</select>
					</div>
				</div>
				<div className="flex items-center gap-2">
					<div className="sm:hidden">
						<label className="text-xs text-gray-500 mr-2">Filter:</label>
						<select
							value={matchFilter}
							onChange={(e) => setMatchFilter(e.target.value ? Number(e.target.value) : '')}
							className="border border-gray-300 rounded px-2 py-1 text-sm"
						>
							<option value="">All matches</option>
							{matches.map((m) => (
								<option key={m.id} value={m.id}>#{m.id} {m.team1} vs {m.team2}</option>
							))}
						</select>
					</div>
					<button
						onClick={recalculateAll}
						disabled={recalcAllLoading}
						className="inline-flex items-center gap-2 bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
					>
						{recalcAllLoading ? (
							<div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
						) : (
							<svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
							</svg>
						)}
						Recalculate All
					</button>
				</div>
				{matchFilter !== '' && (
					<button
						onClick={() => setMatchFilter('')}
						className="px-3 py-1 border rounded text-sm text-gray-700 hover:bg-gray-50"
					>
						Clear
					</button>
				)}
			</div>

			<div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
				{(() => {
					const filtered = matchFilter === '' ? matches : matches.filter((m) => m.id === matchFilter);
					return filtered.map((match) => (
					<div
						key={match.id}
						className="bg-white rounded-2xl shadow-sm p-5 flex flex-col gap-3 hover:shadow-md transition-shadow"
					>
						<div className="flex items-center justify-between">
							<span className="text-xs text-gray-400 font-medium">Match #{match.id}</span>
							{statusBadge(match.status)}
						</div>
						<div className="text-center">
							<p className="text-lg font-bold text-gray-800">
								{match.team1} <span className="text-gray-400 font-normal">vs</span> {match.team2}
							</p>
							<p className="text-sm text-gray-500 mt-1">
								{match.match_date} at {match.match_time}
							</p>
						</div>
						<div className="mt-auto flex flex-col gap-2">
							<button
								onClick={() => validateCompute(match.id)}
								disabled={validating[match.id]}
								className="w-full inline-flex items-center justify-center gap-2 bg-amber-50 text-amber-700 border border-amber-200 px-4 py-2 rounded-lg text-sm font-medium hover:bg-amber-100 disabled:opacity-50 transition-colors"
							>
								{validating[match.id] ? (
									<div className="animate-spin rounded-full h-4 w-4 border-b-2 border-amber-600" />
								) : (
									<svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
									</svg>
								)}
								{validating[match.id] ? 'Validating...' : 'Validate Compute'}
							</button>
							<button
								onClick={() => recalculate(match.id)}
								disabled={recalculating[match.id]}
								className="w-full inline-flex items-center justify-center gap-2 bg-gray-100 text-gray-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-200 disabled:opacity-50 transition-colors"
							>
								{recalculating[match.id] ? (
									<div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600" />
								) : (
									<svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
									</svg>
								)}
								{recalculating[match.id] ? 'Recalculating...' : 'Recalculate'}
							</button>
						</div>
						{validateResult[match.id] && (
							<div className={`mt-2 p-3 rounded-lg text-xs ${validateResult[match.id].safe_to_recompute ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'}`}>
								<div className="flex items-center gap-2 mb-1">
									<span className={`font-bold ${validateResult[match.id].safe_to_recompute ? 'text-green-700' : 'text-red-700'}`}>
										{validateResult[match.id].safe_to_recompute ? 'Safe to recompute' : 'NOT SAFE — Data loss detected'}
									</span>
								</div>
								<p className="text-gray-600">
									Stored: {validateResult[match.id].stored_total} | Computed: {validateResult[match.id].computed_total} | Diff: {validateResult[match.id].total_diff}
								</p>
								<p className="text-gray-600">
									ESPN fetched: {validateResult[match.id].espn_fetched ? 'Yes' : 'No'} | Dot balls in HTML: {validateResult[match.id].espn_has_dot_balls ? 'Yes' : 'No'}
								</p>
								{validateResult[match.id].dot_ball_players?.length > 0 && (
									<details className="mt-2">
										<summary className="cursor-pointer text-gray-500 hover:text-gray-700">Dot ball breakdown ({validateResult[match.id].dot_ball_players.length} bowlers)</summary>
										<div className="mt-1 space-y-0.5">
											{validateResult[match.id].dot_ball_players.map((p: any, i: number) => (
												<div key={i} className="text-gray-600">{p.name}: {p.dot_balls} dots ({p.overs} ov, {p.wickets}w)</div>
											))}
										</div>
									</details>
								)}
							</div>
						)}
					</div>
					));
				})()}
				{matches.length === 0 && (
					<div className="col-span-full text-center text-gray-400 py-12">
						No matches found.
					</div>
				)}
			</div>

			{/* Admin Submit Team Section */}
			<div className="mt-8 bg-white rounded-2xl shadow-sm p-5">
				<h2 className="text-lg font-bold text-gray-800 mb-1">Submit Team for User</h2>
				<p className="text-sm text-gray-500 mb-4">Pick 11 players, captain, and vice-captain on behalf of a user.</p>

				<div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
					<div>
						<label className="block text-sm font-medium text-gray-700 mb-1">User</label>
						<select
							value={selectedUserId}
							onChange={(e) => setSelectedUserId(e.target.value ? Number(e.target.value) : '')}
							className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
						>
							<option value="">Select user...</option>
							{users.map((u) => (
								<option key={u.id} value={u.id}>{u.name} ({u.email})</option>
							))}
						</select>
					</div>
					<div>
						<label className="block text-sm font-medium text-gray-700 mb-1">Match</label>
						<select
							value={selectedMatchId}
							onChange={(e) => setSelectedMatchId(e.target.value ? Number(e.target.value) : '')}
							className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
						>
							<option value="">Select match...</option>
							{matches.map((m) => (
								<option key={m.id} value={m.id}>#{m.id} {m.team1} vs {m.team2}</option>
							))}
						</select>
					</div>
				</div>

				<div className="mb-2 text-sm text-gray-600 font-medium">
					Players ({selectedPlayers.size}/11 selected)
				</div>
				<div className="max-h-64 overflow-y-auto border border-gray-200 rounded-lg mb-4">
					{players.map((p) => {
						const checked = selectedPlayers.has(p.id);
						return (
							<label
								key={p.id}
								className={`flex items-center gap-3 px-3 py-2 text-sm cursor-pointer hover:bg-gray-50 border-b border-gray-100 last:border-b-0 ${checked ? 'bg-indigo-50' : ''}`}
							>
								<input
									type="checkbox"
									checked={checked}
									onChange={() => togglePlayer(p.id)}
									className="rounded text-indigo-600"
								/>
								<span className="flex-1">{p.name}</span>
								<span className="text-xs text-gray-400">{p.team} - {p.role}</span>
								{checked && (
									<span className="flex items-center gap-2">
										<label className="flex items-center gap-1 text-xs">
											<input
												type="radio"
												name="captain"
												checked={captainId === p.id}
												onChange={() => setCaptainId(p.id)}
												className="text-indigo-600"
											/>
											C
										</label>
										<label className="flex items-center gap-1 text-xs">
											<input
												type="radio"
												name="viceCaptain"
												checked={viceCaptainId === p.id}
												onChange={() => setViceCaptainId(p.id)}
												className="text-indigo-600"
											/>
											VC
										</label>
									</span>
								)}
							</label>
						);
					})}
				</div>

				<button
					onClick={handleSubmitTeam}
					disabled={submitTeamLoading || selectedPlayers.size !== 11 || !captainId || !viceCaptainId || captainId === viceCaptainId || !selectedUserId || !selectedMatchId}
					className="inline-flex items-center gap-2 bg-indigo-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
				>
					{submitTeamLoading ? (
						<div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
					) : null}
					Submit Team
				</button>
			</div>
		</div>
	);
}

