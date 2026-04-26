import { useCallback, useEffect, useRef, useState } from 'react';
import client from '../api/client';

type RuntimeCurrentTime = {
  iso?: string;
  overridden?: boolean;
};

type AppClockState = {
  nowMs: number;
  syncedAtMs: number;
  overridden: boolean;
};

function createFallbackState(): AppClockState {
  const nowMs = Date.now();
  return {
    nowMs,
    syncedAtMs: nowMs,
    overridden: false,
  };
}

export function useAppClock() {
  const [clock, setClock] = useState<AppClockState>(createFallbackState);
  const clockRef = useRef(clock);

  useEffect(() => {
    clockRef.current = clock;
  }, [clock]);

  const syncClock = useCallback(async () => {
    try {
      const res = await client.get<RuntimeCurrentTime>('/api/runtime/current-time');
      const parsed = res.data?.iso ? new Date(res.data.iso).getTime() : NaN;
      if (!Number.isFinite(parsed)) {
        throw new Error('Invalid runtime clock payload');
      }

      const syncedAtMs = Date.now();
      setClock({
        nowMs: parsed,
        syncedAtMs,
        overridden: Boolean(res.data?.overridden),
      });
    } catch {
      setClock(createFallbackState());
    }
  }, []);

  useEffect(() => {
    let alive = true;
    let tickId: ReturnType<typeof setInterval> | null = null;

    void syncClock();

    tickId = setInterval(() => {
      if (!alive) return;
      setClock((current) => {
        const elapsed = Date.now() - current.syncedAtMs;
        return {
          ...current,
          nowMs: current.nowMs + elapsed,
          syncedAtMs: Date.now(),
        };
      });
    }, 1000);

    return () => {
      alive = false;
      if (tickId) clearInterval(tickId);
    };
  }, [syncClock]);

  const getNow = useCallback(() => new Date(clockRef.current.nowMs), []);

  const now = new Date(clock.nowMs);
  const todayIST = now.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });

  return {
    now,
    nowMs: clock.nowMs,
    todayIST,
    overridden: clock.overridden,
    getNow,
  };
}
