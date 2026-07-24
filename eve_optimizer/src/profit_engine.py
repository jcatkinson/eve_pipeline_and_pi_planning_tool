# DEPRECATED — use src.core.profit_engine instead.
# This shim preserves backward compatibility for scripts using the old import path.
from src.core.profit_engine import *  # noqa: F401, F403
from src.core.profit_engine import ProfitEngine, DecisionResult, MaterialPrice  # noqa: F401
