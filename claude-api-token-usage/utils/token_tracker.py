import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Optional

PRICING = {
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-opus-4-7": {
        "input": 15.00,
        "output": 75.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.00,
        "cache_write": 1.00,
        "cache_read": 0.08,
    },
}

WARN_THRESHOLDS = [0.80, 0.90]
HALT_THRESHOLD = 0.95

# Rate-limit header names returned by the Anthropic API on every response
_HEADER_TOKENS_LIMIT = "anthropic-ratelimit-tokens-limit"
_HEADER_TOKENS_REMAINING = "anthropic-ratelimit-tokens-remaining"
_HEADER_TOKENS_RESET = "anthropic-ratelimit-tokens-reset"
_HEADER_REQUESTS_LIMIT = "anthropic-ratelimit-requests-limit"


class ExecutionHaltedError(Exception):
    pass


class TokenUsageTracker:
    def __init__(
        self,
        model: str,
        token_limit: Optional[int] = None,
        cost_limit: Optional[float] = None,
        log_path: Optional[str] = None,
        slack_webhook_url: Optional[str] = None,
        notify_desktop: bool = False,
    ):
        self.model = model
        self.log_path = log_path
        self.slack_webhook_url = slack_webhook_url
        self.notify_desktop = notify_desktop

        # Limits: set manually here, or auto-detected from API headers on first call
        self.token_limit: Optional[int] = token_limit
        self.cost_limit: Optional[float] = cost_limit
        self._limit_source: str = "manual" if (token_limit or cost_limit) else "pending"

        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_write_tokens = 0
        self.cache_read_tokens = 0
        self.halted = False
        self._halt_reason: Optional[str] = None
        self._warned_thresholds: set = set()

        # Rolling window state — updated from response headers after each call
        self.tokens_remaining: Optional[int] = None
        self.rate_limit_reset: Optional[str] = None  # ISO 8601 timestamp

    def detect_limits_from_headers(self, headers) -> None:
        """
        Read Anthropic rate-limit headers from every response.
        - On the first call (when limits are pending): auto-sets token_limit and cost_limit.
        - On every call: updates tokens_remaining and rate_limit_reset for pre-check use.
        """
        # Always refresh the rolling window state
        try:
            remaining_raw = headers.get(_HEADER_TOKENS_REMAINING)
            if remaining_raw:
                self.tokens_remaining = int(remaining_raw)
            reset_raw = headers.get(_HEADER_TOKENS_RESET)
            if reset_raw:
                self.rate_limit_reset = reset_raw
        except (ValueError, TypeError):
            pass

        # One-time limit detection (skipped if already set manually or previously detected)
        if self._limit_source != "pending":
            return

        raw = headers.get(_HEADER_TOKENS_LIMIT)
        if not raw:
            return

        try:
            token_limit = int(raw)
        except (ValueError, TypeError):
            return

        rates = PRICING.get(self.model, PRICING["claude-sonnet-4-6"])
        blended_rate = (rates["input"] + rates["output"]) / 2
        cost_limit = round((token_limit / 1_000_000) * blended_rate, 4)

        self.token_limit = token_limit
        self.cost_limit = cost_limit
        self._limit_source = "auto"
        print(
            f"[Tracker] Limits auto-detected from API headers — "
            f"Token limit: {token_limit:,} tokens/min | "
            f"Cost ceiling: ${cost_limit:.4f} (blended {self.model} rate)"
        )

    def check_estimate(self, input_tokens: int, max_output_tokens: int) -> dict:
        """
        Compare a pre-call token estimate against the remaining rate-limit window budget.
        Returns an estimate dict and prints a warning if the call is likely to exceed
        the remaining window. Advisory only — never blocks execution.
        """
        estimated_total = input_tokens + max_output_tokens
        tokens_remaining = self.tokens_remaining
        will_likely_exceed = (
            tokens_remaining is not None and estimated_total > tokens_remaining
        )

        if will_likely_exceed:
            reset_info = f", resets at {self.rate_limit_reset}" if self.rate_limit_reset else ""
            msg = (
                f"PRE-CHECK WARNING: Estimated call (~{estimated_total:,} tokens) "
                f"exceeds remaining window budget ({tokens_remaining:,} tokens remaining{reset_info}). "
                "This call may be rate-limited."
            )
            print(f"\n⚠️  {msg}")
            self._notify("Claude Token Tracker — Pre-check Warning", msg)

        return {
            "input_tokens": input_tokens,
            "max_output_tokens": max_output_tokens,
            "estimated_total": estimated_total,
            "tokens_remaining": tokens_remaining,
            "rate_limit_reset": self.rate_limit_reset,
            "will_likely_exceed": will_likely_exceed,
        }

    def track(self, response) -> "TokenUsageTracker":
        usage = response.usage
        self.calls += 1
        self.input_tokens += getattr(usage, "input_tokens", 0)
        self.output_tokens += getattr(usage, "output_tokens", 0)
        self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0)
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0)

        call_input = getattr(usage, "input_tokens", 0)
        call_output = getattr(usage, "output_tokens", 0)
        call_total = self.total_tokens()
        cost = self.estimate_cost()

        token_pct = (call_total / self.token_limit * 100) if self.token_limit else None
        cost_pct_str = f"${cost:.4f} / ${self.cost_limit:.4f}" if self.cost_limit else f"${cost:.4f}"
        token_pct_str = f"{call_total:,} ({token_pct:.1f}%)" if token_pct is not None else f"{call_total:,}"

        print(
            f"[Call {self.calls}] Tokens: {call_input:,} in / {call_output:,} out | "
            f"Cost: ${cost:.4f} | Total: {token_pct_str}"
        )

        self._check_limits()
        return self

    def can_proceed(self) -> bool:
        return not self.halted

    def _check_limits(self):
        token_pct = (self.total_tokens() / self.token_limit) if self.token_limit else None
        cost_pct = (self.estimate_cost() / self.cost_limit) if self.cost_limit else None

        for threshold in WARN_THRESHOLDS:
            key_token = f"token_{threshold}"
            key_cost = f"cost_{threshold}"

            if token_pct is not None and token_pct >= threshold and key_token not in self._warned_thresholds:
                self._warned_thresholds.add(key_token)
                msg = (
                    f"WARNING: Token usage at {token_pct*100:.1f}% of limit "
                    f"({self.total_tokens():,} / {self.token_limit:,} tokens)."
                )
                print(f"\n⚠️  {msg}")
                self._notify("Claude Token Tracker — Warning", msg)

            if cost_pct is not None and cost_pct >= threshold and key_cost not in self._warned_thresholds:
                self._warned_thresholds.add(key_cost)
                msg = (
                    f"WARNING: Cost usage at {cost_pct*100:.1f}% of limit "
                    f"(${self.estimate_cost():.4f} / ${self.cost_limit:.4f})."
                )
                print(f"\n⚠️  {msg}")
                self._notify("Claude Token Tracker — Warning", msg)

        halt_reasons = []
        if token_pct is not None and token_pct >= HALT_THRESHOLD:
            halt_reasons.append(f"tokens at {token_pct*100:.1f}% ({self.total_tokens():,} / {self.token_limit:,})")
        if cost_pct is not None and cost_pct >= HALT_THRESHOLD:
            halt_reasons.append(f"cost at {cost_pct*100:.1f}% (${self.estimate_cost():.4f} / ${self.cost_limit:.4f})")

        if halt_reasons and not self.halted:
            self.halted = True
            self._halt_reason = " and ".join(halt_reasons)
            msg = (
                f"HALT: {self._halt_reason}. "
                "Current execution completed. No new executions will be run."
            )
            print(f"\n⚠️  {msg}\n")
            self._notify("Claude Token Tracker — HALT", msg)

    def _notify(self, title: str, message: str):
        if self.slack_webhook_url:
            try:
                cost = self.estimate_cost()
                slack_text = (
                    f"[{title}] {message}\n"
                    f"Model: {self.model} | "
                    f"Tokens: {self.total_tokens():,}"
                    + (f" / {self.token_limit:,}" if self.token_limit else "")
                    + f" | Cost: ${cost:.4f}"
                    + (f" / ${self.cost_limit:.4f}" if self.cost_limit else "")
                )
                payload = json.dumps({"text": slack_text}).encode("utf-8")
                req = urllib.request.Request(
                    self.slack_webhook_url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=5)
                print("   → Slack notified", end="")
            except Exception as e:
                print(f"   → Slack notification failed: {e}", end="")

        if self.notify_desktop:
            try:
                from plyer import notification
                notification.notify(title=title, message=message, timeout=8)
                print(" | Desktop notification sent", end="")
            except Exception as e:
                print(f" | Desktop notification failed: {e}", end="")

        if self.slack_webhook_url or self.notify_desktop:
            print()

    def estimate_cost(self) -> float:
        rates = PRICING.get(self.model, PRICING["claude-sonnet-4-6"])
        return (
            self.input_tokens * rates["input"] / 1_000_000
            + self.output_tokens * rates["output"] / 1_000_000
            + self.cache_write_tokens * rates["cache_write"] / 1_000_000
            + self.cache_read_tokens * rates["cache_read"] / 1_000_000
        )

    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def summary(self) -> dict:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": self.model,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "total_tokens": self.total_tokens(),
            "estimated_cost_usd": round(self.estimate_cost(), 6),
            "token_limit": self.token_limit,
            "cost_limit": self.cost_limit,
            "limit_source": self._limit_source,
            "halted": self.halted,
            "halt_reason": self._halt_reason,
        }

    def print_summary(self):
        s = self.summary()
        token_pct = (
            f" ({s['total_tokens'] / self.token_limit * 100:.1f}% of {self.token_limit:,})"
            if self.token_limit else ""
        )
        cost_pct = (
            f" ({s['estimated_cost_usd'] / self.cost_limit * 100:.1f}% of ${self.cost_limit:.4f})"
            if self.cost_limit else ""
        )
        limit_src = f" [{s['limit_source']}]" if s["limit_source"] != "pending" else " [not set]"
        status = f"HALTED ({self._halt_reason})" if self.halted else "OK"

        width = 48
        border = "═" * width
        print(f"\n╔{border}╗")
        print(f"║{'Token Usage Summary':^{width}}║")
        print(f"╠{border}╣")
        for label, value in [
            ("Model",          s["model"]),
            ("Limit Source",   s["limit_source"]),
            ("API Calls",      str(s["calls"])),
            ("Input Tokens",   f"{s['input_tokens']:,}"),
            ("Output Tokens",  f"{s['output_tokens']:,}"),
            ("Cache Write",    f"{s['cache_write_tokens']:,}"),
            ("Cache Read",     f"{s['cache_read_tokens']:,}"),
            ("Total Tokens",   f"{s['total_tokens']:,}{token_pct}"),
            ("Estimated $",    f"${s['estimated_cost_usd']:.4f}{cost_pct}"),
            ("Status",         status),
        ]:
            line = f"  {label:<15}: {value}"
            print(f"║{line:<{width}}║")
        print(f"╚{border}╝\n")

    def log_to_file(self, path: Optional[str] = None):
        target = path or self.log_path
        if not target:
            return
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(self.summary()) + "\n")

    def reset(self):
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_write_tokens = 0
        self.cache_read_tokens = 0
        self.halted = False
        self._halt_reason = None
        self._warned_thresholds = set()
        self.tokens_remaining = None
        self.rate_limit_reset = None
        # Retain detected limits and their source across sessions
