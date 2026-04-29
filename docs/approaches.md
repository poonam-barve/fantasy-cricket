  Approach 1: Smart Sleep (Option A from before)

  How: Threads still run forever, but calculate sleep duration dynamically.

  No match today? Sleep 6 hours.
  Match in 3 hours? Sleep 2h 45min.
  Match live? Sleep 60s (normal).

  ┌──────────────────────────────────────────────────────────┬───────────────────────────────────────────────────┐
  │                           Pros                           │                       Cons                        │
  ├──────────────────────────────────────────────────────────┼───────────────────────────────────────────────────┤
  │ Smallest code change (~10 lines)                         │ Threads still exist 24/7                          │
  ├──────────────────────────────────────────────────────────┼───────────────────────────────────────────────────┤
  │ No lifecycle management                                  │ Still waking up unnecessarily (just less often)   │
  ├──────────────────────────────────────────────────────────┼───────────────────────────────────────────────────┤
  │ Zero risk of "forgot to start" bugs                      │ Not truly idle — thread memory + context switches │
  ├──────────────────────────────────────────────────────────┼───────────────────────────────────────────────────┤
  │ Handles schedule changes naturally (wakes up, re-checks) │                                                   │
  └──────────────────────────────────────────────────────────┴───────────────────────────────────────────────────┘

  Effort: 30 minutes. Risk: Near zero.

  ---
  Approach 2: On-Demand Start/Stop (Option B)

  How: Watcher thread polls every 5-10min. Starts scheduler threads when match approaching, stops when done.

  ┌─────────────────────────────────┬────────────────────────────────────────────────────────┐
  │              Pros               │                          Cons                          │
  ├─────────────────────────────────┼────────────────────────────────────────────────────────┤
  │ Only 1 idle thread instead of 3 │ Thread lifecycle complexity (start/stop/restart)       │
  ├─────────────────────────────────┼────────────────────────────────────────────────────────┤
  │ Clean separation of concerns    │ Race conditions on SCHEDULER_STARTED flags             │
  ├─────────────────────────────────┼────────────────────────────────────────────────────────┤
  │                                 │ Still polling (watcher thread)                         │
  ├─────────────────────────────────┼────────────────────────────────────────────────────────┤
  │                                 │ What if watcher misses a restart? Scheduler stays dead │
  └─────────────────────────────────┴────────────────────────────────────────────────────────┘

  Effort: 2-3 hours. Risk: Medium — thread flag bugs are subtle.

  ---
  Approach 3: Internal Timer (threading.Timer)

  How: At boot, calculate exact delay until 15min before each match. Fire one-shot timer that starts schedulers.

  ┌───────────────────────────┬───────────────────────────────────────────────────────────────┐
  │           Pros            │                             Cons                              │
  ├───────────────────────────┼───────────────────────────────────────────────────────────────┤
  │ Zero CPU until match time │ threading.Timer is unreliable for long delays (hours)         │
  ├───────────────────────────┼───────────────────────────────────────────────────────────────┤
  │ Precise activation        │ Server restart = must re-schedule all timers                  │
  ├───────────────────────────┼───────────────────────────────────────────────────────────────┤
  │ Simple mental model       │ If admin changes match time → must cancel + reschedule timers │
  ├───────────────────────────┼───────────────────────────────────────────────────────────────┤
  │                           │ Python timers drift — not guaranteed accurate over hours      │
  ├───────────────────────────┼───────────────────────────────────────────────────────────────┤
  │                           │ Multiple matches/day need multiple timer coordination         │
  └───────────────────────────┴───────────────────────────────────────────────────────────────┘

  Effort: 1-2 hours. Risk: Medium — timer drift, missed reschedules.

  ---
  Approach 4: Event-Driven (Timer + lifecycle hooks)

  How: SchedulerManager class. Timers for activation, event hooks for deactivation. Daily midnight re-schedule.

  ┌─────────────────────────────────────┬────────────────────────────────────────────────────┐
  │                Pros                 │                        Cons                        │
  ├─────────────────────────────────────┼────────────────────────────────────────────────────┤
  │ Cleanest architecture               │ Most complex code                                  │
  ├─────────────────────────────────────┼────────────────────────────────────────────────────┤
  │ Zero idle CPU                       │ Must hook into every place that changes match data │
  ├─────────────────────────────────────┼────────────────────────────────────────────────────┤
  │ Self-healing (midnight re-schedule) │ Over-engineered for 15 users?                      │
  ├─────────────────────────────────────┼────────────────────────────────────────────────────┤
  │ Handles match completion gracefully │ More things that can break                         │
  ├─────────────────────────────────────┼────────────────────────────────────────────────────┤
  │                                     │ Timer issues same as Approach 3                    │
  └─────────────────────────────────────┴────────────────────────────────────────────────────┘

  Effort: 3-4 hours. Risk: Medium-high — more moving parts.

  ---
  Approach 5: External Cron (Railway cron job)

  How: Railway cron triggers an endpoint on your server before each match.

  ┌────────────────────────┬────────────────────────────────────────────────────────────┐
  │          Pros          │                            Cons                            │
  ├────────────────────────┼────────────────────────────────────────────────────────────┤
  │ Truly decoupled        │ Railway cron = separate container, not your running server │
  ├────────────────────────┼────────────────────────────────────────────────────────────┤
  │ No Python timer issues │ Can't call into your running process's memory              │
  ├────────────────────────┼────────────────────────────────────────────────────────────┤
  │                        │ Match times change → cron can't adapt dynamically          │
  ├────────────────────────┼────────────────────────────────────────────────────────────┤
  │                        │ Minimum Railway cron granularity might not fit             │
  ├────────────────────────┼────────────────────────────────────────────────────────────┤
  │                        │ Adds infra complexity for a simple app                     │
  └────────────────────────┴────────────────────────────────────────────────────────────┘

  Effort: 1-2 hours. Risk: High — wrong tool for the job. Cron jobs spin up a new instance, they can't wake up threads inside your already-running server.

  ---
  Approach 6: Hybrid — Smart Sleep + Stop on Idle

  How: Keep the 3 threads but make two changes:
  1. Smart sleep: When no match active, sleep until 15min before next match
  2. Auto-stop: When a scheduler tick finds 0 eligible matches, thread exits. Boot re-checks on next request or daily timer.

  def start_scheduler(self):
      def run():
          while True:
              summary = self.refresh_scores_once()
              if summary["eligible"] == 0:
                  # How long until next match?
                  sleep_time = self._seconds_until_next_active_match()
                  if sleep_time > 600:  # more than 10 min away
                      # Exit thread — watcher or daily timer will restart
                      SCORE_SCHEDULER_STARTED = False
                      return
                  time.sleep(min(sleep_time, 60))
              else:
                  time.sleep(60)

  ┌───────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────┐
  │                         Pros                          │                          Cons                           │
  ├───────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┤
  │ Best of both worlds                                   │ Slightly more complex than pure smart sleep             │
  ├───────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┤
  │ Threads die when truly idle                           │ Need something to restart them (daily timer or watcher) │
  ├───────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┤
  │ No drift issues (threads run normally when active)    │ Still need the STARTED flag reset logic                 │
  ├───────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┤
  │ Minimal code change                                   │                                                         │
  ├───────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┤
  │ Handles schedule changes (thread just sleeps shorter) │                                                         │
  └───────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────┘

  Effort: 1-1.5 hours. Risk: Low.

  ---
  My Recommendation

  For your app (15 users, 1-2 matches/day, Railway):

  ┌─────────────────────────────┬────────────────────────────────────────────────┐
  │          Approach           │                     Score                      │
  ├─────────────────────────────┼────────────────────────────────────────────────┤
  │ ~~5. External Cron~~        │ Ruled out — can't talk to running process      │
  ├─────────────────────────────┼────────────────────────────────────────────────┤
  │ ~~4. Event-Driven~~         │ Over-engineered for this scale                 │
  ├─────────────────────────────┼────────────────────────────────────────────────┤
  │ ~~2. On-Demand Start/Stop~~ │ Thread lifecycle bugs not worth it             │
  ├─────────────────────────────┼────────────────────────────────────────────────┤
  │ 3. Internal Timer           │ Works but timer drift risk                     │
  ├─────────────────────────────┼────────────────────────────────────────────────┤
  │ 1. Smart Sleep              │ Simple, safe, 90% of the benefit               │
  ├─────────────────────────────┼────────────────────────────────────────────────┤
  │ 6. Hybrid                   │ Best balance if you want threads to fully stop │
  └─────────────────────────────┴────────────────────────────────────────────────┘

  If you want minimal risk: Go with Approach 1 (Smart Sleep). 10 lines of code, threads sleep for hours instead of 60 seconds, virtually zero idle CPU.

  If you want threads to actually die when not needed: Go with Approach 6 (Hybrid) — smart sleep when match is approaching, thread exits when nothing for hours, a simple daily timer at midnight re-schedules
  everything.

  Both are clean. What do you think?