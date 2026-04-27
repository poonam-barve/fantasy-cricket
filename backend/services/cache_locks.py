from __future__ import annotations

import threading

# Shared lock for all cache writes so refresh jobs serialize cleanly.
CACHE_WRITE_LOCK = threading.Lock()
