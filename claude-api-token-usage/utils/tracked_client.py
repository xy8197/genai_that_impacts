import sys
from typing import Optional
import anthropic

from .auth import resolve_api_key
from .token_tracker import TokenUsageTracker, ExecutionHaltedError


# Parameters accepted by messages.create() but NOT by messages.count_tokens()
_COUNT_TOKENS_STRIP = {"max_tokens", "temperature", "top_p", "top_k", "stream", "stop_sequences", "metadata"}


class _TrackedMessages:
    """Proxy for client.messages that intercepts create() calls."""

    def __init__(self, client: anthropic.Anthropic, tracker: TokenUsageTracker, auto_pre_check: bool):
        self._client = client
        self.tracker = tracker
        self.auto_pre_check = auto_pre_check

    def pre_check(self, **kwargs) -> dict:
        """
        Estimate token usage for a call before executing it.
        Calls the Anthropic count_tokens API (no cost, no generation) and compares
        the estimate against the remaining rate-limit window budget.
        Returns the estimate dict and prints a warning if the call may be rate-limited.
        """
        count_kwargs = {k: v for k, v in kwargs.items() if k not in _COUNT_TOKENS_STRIP}
        max_output_tokens = kwargs.get("max_tokens", 0)

        count_response = self._client.messages.count_tokens(**count_kwargs)
        input_tokens = count_response.input_tokens

        return self.tracker.check_estimate(input_tokens, max_output_tokens)

    def create(self, *args, **kwargs) -> anthropic.types.Message:
        if not self.tracker.can_proceed():
            raise ExecutionHaltedError(
                f"Execution halted: {self.tracker._halt_reason}. "
                "No API call was made. Call tracker.reset() to start a new session."
            )

        # Keep tracker model in sync if the caller switches models mid-session
        if "model" in kwargs:
            self.tracker.model = kwargs["model"]

        if self.auto_pre_check:
            self.pre_check(**kwargs)

        # Use with_raw_response to capture rate-limit headers for auto limit detection
        raw = self._client.messages.with_raw_response.create(*args, **kwargs)
        response = raw.parse()

        # Update limits (first call) and rolling window state (every call)
        self.tracker.detect_limits_from_headers(raw.headers)
        self.tracker.track(response)
        return response

    def __getattr__(self, name):
        return getattr(self._client.messages, name)


class TrackedAnthropicClient:
    """
    Drop-in wrapper around anthropic.Anthropic that automatically tracks
    token usage and cost on every messages.create() call.

    Auth:
        API key is resolved automatically in this order:
          1. Explicit api_key= argument
          2. ANTHROPIC_API_KEY environment variable
        If neither is found, a context-aware message is printed explaining how to
        obtain a key (with extra guidance when running inside Claude Code).

    Token and cost limits are auto-detected from the Anthropic API rate-limit
    headers returned on the first call (based on your subscription tier).
    You can override them explicitly via token_limit / cost_limit if needed.

    Pre-call estimation (two options — choose one or combine):
      Option A — Explicit:  call client.messages.pre_check(**kwargs) before create()
      Option B — Automatic: set auto_pre_check=True to run it inside every create()

    Usage:
        # Zero-config (auto-detect limits, no pre-check)
        client = TrackedAnthropicClient(log_path="logs/usage.jsonl")

        # Option B: automatic pre-check on every call
        client = TrackedAnthropicClient(auto_pre_check=True, log_path="logs/usage.jsonl")

        # Option A: explicit pre-check before a specific call
        client.messages.pre_check(model="claude-sonnet-4-6", messages=[...], max_tokens=500)
        response = client.messages.create(model="claude-sonnet-4-6", ...)
        client.tracker.print_summary()
    """

    def __init__(
        self,
        *args,
        token_limit: Optional[int] = None,
        cost_limit: Optional[float] = None,
        log_path: Optional[str] = None,
        slack_webhook_url: Optional[str] = None,
        notify_desktop: bool = False,
        auto_pre_check: bool = False,
        **kwargs,
    ):
        api_key = resolve_api_key(kwargs.pop("api_key", None))
        if not api_key:
            sys.exit(1)
        self._client = anthropic.Anthropic(*args, api_key=api_key, **kwargs)

        # Use the default model as a starting point; updated per-call if model kwarg changes
        default_model = "claude-sonnet-4-6"
        self.tracker = TokenUsageTracker(
            model=default_model,
            token_limit=token_limit,
            cost_limit=cost_limit,
            log_path=log_path,
            slack_webhook_url=slack_webhook_url,
            notify_desktop=notify_desktop,
        )
        self.messages = _TrackedMessages(self._client, self.tracker, auto_pre_check=auto_pre_check)

    def __getattr__(self, name):
        return getattr(self._client, name)
