import { Link } from 'react-router-dom';
import { useState, useEffect } from 'react';
import client from '../api/client';
import { useAuth } from '../auth/AuthContext';

interface AchievementEntry {
  user_id: number;
  name: string;
  value: number;
}

interface AchievementCategory {
  title: string;
  icon: string;
  entries: AchievementEntry[];
}

const ICON_MAP: Record<string, { emoji: string; color: string; bg: string }> = {
  gold: { emoji: '🥇', color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/20' },
  silver: { emoji: '🥈', color: 'text-gray-300', bg: 'bg-gray-400/10 border-gray-400/20' },
  bronze: { emoji: '🥉', color: 'text-amber-600', bg: 'bg-amber-700/10 border-amber-700/20' },
  medals: { emoji: '🏅', color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' },
  trophy: { emoji: '🏆', color: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/20' },
  points: { emoji: '⭐', color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
  fire: { emoji: '🔥', color: 'text-orange-400', bg: 'bg-orange-500/10 border-orange-500/20' },
};

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
          const rankColors = ['text-yellow-400', 'text-gray-300', 'text-amber-600', 'text-white/50', 'text-white/40'];
          return (
            <div
              key={entry.user_id}
              className={`flex items-center justify-between px-3 py-1.5 rounded-xl ${
                isMe ? 'bg-white/10 ring-1 ring-white/20' : ''
              }`}
            >
              <div className="flex items-center gap-2.5">
                <span className={`text-xs font-bold w-4 ${rankColors[i] || 'text-white/40'}`}>
                  {i + 1}
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
  const [loading, setLoading] = useState(true);
  const { profile } = useAuth();

  useEffect(() => {
    const fetch = async () => {
      try {
        const res = await client.get('/api/achievements');
        setCategories(res.data?.categories || []);
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
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {categories.map((cat) => (
            <CategoryCard key={cat.title} category={cat} myUserId={profile?.id ?? null} />
          ))}
        </div>
      )}
    </div>
  );
}
