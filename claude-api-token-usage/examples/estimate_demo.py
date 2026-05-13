"""
Token & Cost Estimator — for claude.ai Pro / Claude Code users.

No API key required. Estimates token usage and cost locally using tiktoken,
so you can size prompts and understand API costs before committing to API access.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import TokenEstimator
from utils.token_tracker import PRICING

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-6"   # change to any supported model
MAX_TOKENS = 500               # worst-case output tokens per call

SYSTEM_PROMPT = (
    "You are a concise assistant. Always answer in one sentence."
)

MESSAGES_TO_ESTIMATE = [
    [{"role": "user", "content": "What is prompt caching in LLMs?"}],
    [{"role": "user", "content": "Explain the difference between RAG and fine-tuning in simple terms."}],
    [
        {"role": "user", "content": "What is an embedding?"},
        {"role": "assistant", "content": "An embedding is a numerical vector that represents text in a high-dimensional space."},
        {"role": "user", "content": "How are embeddings used in semantic search?"},
    ],
]

# ---------------------------------------------------------------------------
# Estimate
# ---------------------------------------------------------------------------

print(f"\nToken & Cost Estimator")
print(f"Model: {MODEL} | Max output tokens per call: {MAX_TOKENS}")
print(f"Pricing: ${PRICING[MODEL]['input']}/M input · ${PRICING[MODEL]['output']}/M output")
print("─" * 60)

estimator = TokenEstimator(model=MODEL, log_path="logs/estimates.jsonl")

total_input_tokens = 0
total_cost = 0.0

for i, messages in enumerate(MESSAGES_TO_ESTIMATE, 1):
    result = estimator.estimate(messages, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT)
    total_input_tokens += result["estimated_input_tokens"]
    total_cost += result["estimated_total_cost_usd"]

    last_user_msg = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
    )
    print(f"\nCall {i}: \"{last_user_msg[:60]}{'...' if len(last_user_msg) > 60 else ''}\"")
    estimator.print_estimate(result)
    estimator.log_to_file(result)

print("─" * 60)
print(f"  Total across {len(MESSAGES_TO_ESTIMATE)} calls:")
print(f"    ~{total_input_tokens:,} input tokens")
print(f"    ~${total_cost:.6f} estimated total cost")
print(f"\n  Estimates logged to: {os.path.abspath('logs/estimates.jsonl')}\n")
