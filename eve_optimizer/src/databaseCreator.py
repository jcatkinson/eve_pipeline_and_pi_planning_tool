# DEPRECATED — use src.core.database instead.
# This shim preserves backward compatibility for scripts using the old import path.
from src.core.database import *  # noqa: F401, F403
from src.core.database import build_database, PI_CHAINS  # noqa: F401
