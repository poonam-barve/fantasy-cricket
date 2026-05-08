import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import client from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useToast } from '../components/Toast';

export default function SettingsPage() {
  const navigate = useNavigate();
  const { profile, refreshProfile } = useAuth();
  const { toast } = useToast();
  const [name, setName] = useState('');
  const [replaceSubstitutesWithBackups, setReplaceSubstitutesWithBackups] = useState(true);
  const [saving, setSaving] = useState(false);
  const backupModes = [
    {
      key: true,
      title: 'Unavailable + substitutes',
      description: 'Default',
    },
    {
      key: false,
      title: 'Unavailable only',
      description: 'Opt out',
    },
  ] as const;

  useEffect(() => {
    setName(profile?.name || '');
    setReplaceSubstitutesWithBackups(profile?.replace_substitutes_with_backups ?? true);
  }, [profile?.name, profile?.replace_substitutes_with_backups]);

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    const cleanedName = name.trim();
    if (!cleanedName) {
      toast('Name is required.', 'error');
      return;
    }

    setSaving(true);
    try {
      await client.patch('/api/auth/me', {
        name: cleanedName,
        replace_substitutes_with_backups: replaceSubstitutesWithBackups,
      });
      await refreshProfile();
      toast('Settings updated!', 'success');
      navigate('/dashboard');
    } catch (err: any) {
      toast(err?.response?.data?.detail || 'Failed to update name.', 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-xl px-4 py-4">
      <div className="mb-6 flex items-center gap-3">
        <Link to="/dashboard" className="rounded-xl p-2 transition-all hover:bg-white/10">
          <svg className="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </Link>
        <div>
          <h1 className="text-lg font-bold text-white">Settings</h1>
          <p className="text-xs text-white/45">Update your display name and backup preference.</p>
        </div>
      </div>

      <form onSubmit={handleSave} className="rounded-2xl border border-white/10 bg-white/5 p-5">
        <label className="block text-sm font-medium text-white/80" htmlFor="display-name">
          Display Name
        </label>
        <input
          id="display-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={50}
          className="mt-2 w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-white outline-none transition-all placeholder:text-white/25 focus:border-green-500/40"
          placeholder="Your name"
        />
        <p className="mt-2 text-xs text-white/35">This name is shown across the app.</p>

        <div className="mt-6 rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="mb-3">
            <p className="text-sm font-medium text-white/85">Backup behavior at match start</p>
            <p className="mt-1 text-xs text-white/40">
              Choose how backups should be applied when the playing XI is finalized.
            </p>
          </div>

          <div
            role="radiogroup"
            aria-label="Backup behavior at match start"
            className="grid gap-2 rounded-2xl border border-white/10 bg-black/20 p-1.5 sm:grid-cols-2"
          >
            {backupModes.map((mode) => {
              const selected = replaceSubstitutesWithBackups === mode.key;
              return (
                <button
                  key={mode.title}
                  type="button"
                  onClick={() => setReplaceSubstitutesWithBackups(mode.key)}
                  className={`rounded-xl border px-4 py-3 text-left transition-all ${
                    selected
                      ? 'border-emerald-400/40 bg-emerald-500/15 shadow-sm shadow-emerald-500/10'
                      : 'border-transparent bg-transparent hover:border-white/10 hover:bg-white/5'
                  }`}
                  aria-pressed={selected}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className={`text-sm font-semibold ${selected ? 'text-emerald-200' : 'text-white/80'}`}>
                        {mode.title}
                      </p>
                      <p className={`mt-1 text-[11px] uppercase tracking-[0.16em] ${selected ? 'text-emerald-200/70' : 'text-white/35'}`}>
                        {mode.description}
                      </p>
                    </div>
                    <span
                      className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-all ${
                        selected ? 'border-emerald-300/40 bg-emerald-400' : 'border-white/15 bg-white/5'
                      }`}
                      aria-hidden="true"
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full transition-all ${
                          selected ? 'bg-black opacity-100' : 'bg-transparent opacity-0'
                        }`}
                      />
                    </span>
                  </div>
                </button>
              );
            })}
          </div>

          <div className="mt-3 text-xs text-white/35">
            Current setting:{' '}
            {replaceSubstitutesWithBackups ? 'Backups can replace substitutes' : 'Backups only replace unavailable players'}
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={() => navigate('/dashboard')}
            className="rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-white/75 transition-all hover:bg-white/10"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="rounded-xl bg-green-500 px-5 py-2.5 text-sm font-semibold text-black transition-all hover:bg-green-400 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </form>
    </div>
  );
}
