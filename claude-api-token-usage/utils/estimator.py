import json
import os
from datetime import datetime, timezone
from typing import Optional

from .token_tracker import PRICING


class TokenEstimator:
    """
    Estimates token usage and cost for Claude API calls locally — no API key required.

    Intended for claude.ai Pro / Claude Code users who want to understand what a
    given prompt would cost before committing to API access, or to size prompts
    against context windows without making live calls.

    Tokenization uses tiktoken (cl100k_base encoding), which closely approximates
    Claude's tokenizer. Falls back to a character-based approximation (~4 chars/token)
    if tiktoken is not installed.

    Usage:
        estimator = TokenEstimator(model="claude-sonnet-4-6")
        result = estimator.estimate(
            messages=[{"role": "user", "content": "Explain RAG in one sentence."}],
            max_tokens=200,
        )
        estimator.print_estimate(result)
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        log_path: Optional[str] = None,
    ):
        if model not in PRICING:
            supported = ", ".join(PRICING.keys())
            raise ValueError(f"Unknown model '{model}'. Supported: {supported}")

        self.model = model
        self.log_path = log_path
        self._encoder = self._load_encoder()

    def _load_encoder(self):
        try:
            import tiktoken
            return tiktoken.get_encoding("cl100k_base")
        except ImportError:
            return None

    @property
    def tokenizer_name(self) -> str:
        return "tiktoken/cl100k_base" if self._encoder else "character_approx (~4 chars/token)"

    def count_tokens(self, text: str) -> int:
        """Count tokens in a plain text string."""
        if self._encoder:
            return len(self._encoder.encode(text))
        return max(1, len(text) // 4)

    def estimate(
        self,
        messages: list,
        max_tokens: int = 0,
        system: Optional[str] = None,
    ) -> dict:
        """
        Estimate token usage and cost for a messages.create() call.

        Args:
            messages:   List of message dicts (same format as the Anthropic SDK).
            max_tokens: Worst-case output tokens (maps to the max_tokens parameter).
                        Set to 0 if you only want to estimate input cost.
            system:     Optional system prompt string.

        Returns:
            A dict with token counts, cost breakdown, and metadata.
        """
        input_tokens = 0

        if system:
            input_tokens += self.count_tokens(system)

        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                input_tokens += self.count_tokens(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        input_tokens += self.count_tokens(block.get("text", ""))
            # ~4 tokens of overhead per message for role + formatting
            input_tokens += 4

        rates = PRICING[self.model]
        input_cost = round(input_tokens * rates["input"] / 1_000_000, 6)
        output_cost = round(max_tokens * rates["output"] / 1_000_000, 6)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": self.model,
            "estimated_input_tokens": input_tokens,
            "max_output_tokens": max_tokens,
            "estimated_input_cost_usd": input_cost,
            "estimated_output_cost_usd": output_cost,
            "estimated_total_cost_usd": round(input_cost + output_cost, 6),
            "tokenizer": self.tokenizer_name,
        }

    def print_estimate(self, result: dict) -> None:
        """Pretty-print an estimate returned by estimate()."""
        width = 52
        border = "═" * width
        accuracy_note = "(±5%)" if self._encoder else "(rough ±20%)"

        print(f"\n╔{border}╗")
        print(f"║{'Token & Cost Estimate':^{width}}║")
        print(f"╠{border}╣")
        for label, value in [
            ("Model",            result["model"]),
            ("Tokenizer",        result["tokenizer"]),
            ("Input Tokens",     f"~{result['estimated_input_tokens']:,} {accuracy_note}"),
            ("Max Output Tokens", f"{result['max_output_tokens']:,}"),
            ("Input Cost",       f"~${result['estimated_input_cost_usd']:.6f}"),
            ("Output Cost",      f"~${result['estimated_output_cost_usd']:.6f}"),
            ("Total Cost",       f"~${result['estimated_total_cost_usd']:.6f}"),
        ]:
            line = f"  {label:<20}: {value}"
            print(f"║{line:<{width}}║")
        print(f"╚{border}╝")
        print(f"  Note: Estimates are local approximations. Actual costs may vary.\n")

    def log_to_file(self, result: dict, path: Optional[str] = None) -> None:
        """Append the estimate dict as a JSON line to a log file."""
        target = path or self.log_path
        if not target:
            return
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(result) + "\n")
