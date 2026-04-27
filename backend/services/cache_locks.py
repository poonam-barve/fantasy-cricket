from __future__ import annotations

import threading

# Shared lock for all cache writes so refresh jobs serialize cleanly.
CACHE_WRITE_LOCK = threading.Lock()

# Shared lock for full refresh cycles so scheduler/admin refreshes don't race.
CACHE_REFRESH_LOCK = threading.RLock()
