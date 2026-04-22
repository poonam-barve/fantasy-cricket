type RankShiftBadgeProps = {
  delta?: number | null;
  compact?: boolean;
  className?: string;
};

export default function RankShiftBadge({ delta, compact = false, className = '' }: RankShiftBadgeProps) {
  if (!delta) return null;

  const up = delta > 0;
  const value = Math.abs(delta);
  const sizeClasses = compact ? 'px-1 py-0.5 text-[9px]' : 'px-1.5 py-0.5 text-[10px]';
  const colorClasses = up
    ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/20'
    : 'bg-rose-500/15 text-rose-300 border-rose-500/20';

  return (
    <span
      className={`inline-flex items-center gap-0.5 rounded-full border font-bold leading-none whitespace-nowrap ${sizeClasses} ${colorClasses} ${className}`}
      aria-label={up ? `Rank up ${value}` : `Rank down ${value}`}
      title={up ? `Rank up ${value}` : `Rank down ${value}`}
    >
      <span>{up ? '▲' : '▼'}</span>
      <span>{value}</span>
    </span>
  );
}
