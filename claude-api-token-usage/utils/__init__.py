from .auth import resolve_api_key, is_claude_code
from .estimator import TokenEstimator
from .token_tracker import TokenUsageTracker, ExecutionHaltedError
from .tracked_client import TrackedAnthropicClient

__all__ = [
    # API users
    "TrackedAnthropicClient",
    "TokenUsageTracker",
    "ExecutionHaltedError",
    # Pro / Claude Code users
    "TokenEstimator",
    # Auth helpers
    "resolve_api_key",
    "is_claude_code",
]
