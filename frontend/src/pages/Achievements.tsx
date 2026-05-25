import { Link } from 'react-router-dom';
import { useState, useEffect } from 'react';
import client from '../api/client';
import { useAuth } from '../auth/AuthContext';

interface AchievementEntry {
  user_id: number;
  name: string;
  value: number;
  rank: number;
}

interface AchievementCategory {
  title: string;
  icon: string;
  entries: AchievementEntry[];
}

interface MyStat {
  value: number;
  rank: number;
}

interface MyStats {
  gold: MyStat;
  silver: MyStat;
  bronze: MyStat;
  total_medals: MyStat;
  knockout_wins: MyStat;
  total_points: MyStat;
  highest_score: MyStat;
  predictions_total: MyStat;
  perfect_strike: MyStat;
  elite_precision: MyStat;
  great_call: MyStat;
}

const ICON_MAP: Record<string, { emoji: string; color: string; bg: string }> = {
  gold: { emoji: '🥇', color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/20' },
  silver: { emoji: '🥈', color: 'text-gray-300', bg: 'bg-gray-400/10 border-gray-400/20' },
  bronze: { emoji: '🥉', color: 'text-amber-600', bg: 'bg-amber-700/10 border-amber-700/20' },
  medals: { emoji: '🏅', color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' },
  trophy: { emoji: '🏆', color: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/20' },
  points: { emoji: '⭐', color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
  fire: { emoji: '🔥', color: 'text-orange-400', bg: 'bg-orange-500/10 border-orange-500/20' },
  predictions: { emoji: '🎯', color: 'text-cyan-400', bg: 'bg-cyan-500/10 border-cyan-500/20' },
  perfect: { emoji: '💎', color: 'text-pink-400', bg: 'bg-pink-500/10 border-pink-500/20' },
  elite: { emoji: '🎯', color: 'text-indigo-400', bg: 'bg-indigo-500/10 border-indigo-500/20' },
  great: { emoji: '👏', color: 'text-teal-400', bg: 'bg-teal-500/10 border-teal-500/20' },
};

const MY_STATS_CONFIG: { key: keyof MyStats; label: string; emoji: string }[] = [
  { key: 'gold', label: 'Gold', emoji: '🥇' },
  { key: 'silver', label: 'Silver', emoji: '🥈' },
  { key: 'bronze', label: 'Bronze', emoji: '🥉' },
  { key: 'total_medals', label: 'Total Medals', emoji: '🏅' },
  { key: 'knockout_wins', label: 'Knockout Wins', emoji: '🏆' },
  { key: 'total_points', label: 'Total Points', emoji: '⭐' },
  { key: 'highest_score', label: 'Best Score', emoji: '🔥' },
  { key: 'predictions_total', label: 'Predictions', emoji: '🎯' },
  { key: 'perfect_strike', label: 'Perfect Strike', emoji: '💎' },
  { key: 'elite_precision', label: 'Elite Precision', emoji: '🎯' },
  { key: 'great_call', label: 'Great Call', emoji: '👏' },
];

function MyAchievements({ stats }: { stats: MyStats }) {
  return (
    <div className="mb-6 rounded-2xl border border-blue-500/20 bg-blue-500/5 p-4">
      <h3 className="text-sm font-bold text-blue-400 mb-3 flex items-center gap-2">
        <span className="text-lg">👤</span> My Achievements
      </h3>
      <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
        {MY_STATS_CONFIG.map(({ key, label, emoji }) => {
          const stat = stats[key];
          if (!stat || stat.value === 0) return null;
          return (
            <div key={key} className="bg-white/5 rounded-xl p-2 text-center">
              <span className="text-sm">{emoji}</span>
              <p className="text-white font-bold text-sm mt-0.5">
                {stat.value % 1 === 0 ? stat.value : stat.value.toFixed(1)}
              </p>
              <p className="text-white/40 text-[10px] leading-tight">{label}</p>
              <p className="text-blue-400/80 text-[10px] font-medium mt-0.5">
                Rank #{stat.rank}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CategoryCard({ category, myUserId }: { category: AchievementCategory; myUserId: number | null }) {
  const style = ICON_MAP[category.icon] || ICON_MAP.points;

  return (
    <div className={`rounded-2xl border p-4 ${style.bg}`}>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xl">{style.emoji}</span>
        <h3 className={`text-sm font-bold ${style.color}`}>{category.title}</h3>
      </div>
      <div className="space-y-2">
        {category.entries.map((entry, i) => {
          const isMe = entry.user_id === myUserId;
          const rankColorMap: Record<number, string> = { 1: 'text-yellow-400', 2: 'text-gray-300', 3: 'text-amber-600' };
          return (
            <div
              key={entry.user_id}
              className={`flex items-center justify-between px-3 py-1.5 rounded-xl ${
                isMe ? 'bg-white/10 ring-1 ring-white/20' : ''
              }`}
            >
              <div className="flex items-center gap-2.5">
                <span className={`text-xs font-bold w-4 ${rankColorMap[entry.rank] || 'text-white/40'}`}>
                  {entry.rank}
                </span>
                <span className="text-sm text-white/90 truncate max-w-[140px]">
                  {entry.name}
                </span>
                {isMe && (
                  <span className="text-[9px] font-bold bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded">
                    YOU
                  </span>
                )}
              </div>
              <span className={`text-sm font-semibold ${style.color}`}>
                {entry.value % 1 === 0 ? entry.value : entry.value.toFixed(1)}
              </span>
            </div>
          );
        })}
        {category.entries.length === 0 && (
          <p className="text-white/30 text-xs text-center py-2">No data yet</p>
        )}
      </div>
    </div>
  );
}

export default function AchievementsPage() {
  const [categories, setCategories] = useState<AchievementCategory[]>([]);
  const [myStats, setMyStats] = useState<MyStats | null>(null);
  const [loading, setLoading] = useState(true);
  const { profile } = useAuth();

  useEffect(() => {
    const fetch = async () => {
      try {
        const res = await client.get('/api/achievements');
        setCategories(res.data?.categories || []);
        setMyStats(res.data?.my_stats || null);
      } catch { /* silent */ }
      finally { setLoading(false); }
    };
    fetch();
  }, []);

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Link to="/dashboard" className="p-2 hover:bg-white/10 rounded-xl transition-colors">
            <svg className="w-5 h-5 text-white/60" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </Link>
          <h2 className="text-xl font-bold text-white">Achievements</h2>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white" />
        </div>
      ) : (
        <>
          {myStats && <MyAchievements stats={myStats} />}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {categories.map((cat) => (
              <CategoryCard key={cat.title} category={cat} myUserId={profile?.id ?? null} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
