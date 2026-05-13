import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import TrackedAnthropicClient, ExecutionHaltedError

API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not API_KEY:
    print("Error: ANTHROPIC_API_KEY environment variable is not set.")
    sys.exit(1)

PROMPTS = [
    "What is prompt caching in LLMs? Answer in one sentence.",
    "What is the difference between tokens and words? One sentence.",
    "Name one benefit of tracking API token usage. One sentence.",
    "What is RAG? One sentence.",
    "What does 'grounding' mean in AI? One sentence.",
]

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 100

# ---------------------------------------------------------------------------
# Pre-check mode: choose ONE of the two options below.
#
# Option A — Explicit pre_check():
#   Call client.messages.pre_check(**kwargs) manually before each create().
#   Use this when you want selective control over which calls are checked.
#
# Option B — auto_pre_check=True:
#   Every create() automatically runs count_tokens first.
#   Use this for zero-touch protection across all calls.
#   Trade-off: adds one extra API round-trip per call.
# ---------------------------------------------------------------------------

# Uncomment ONE of the two client configs below:

# --- Option A: explicit pre_check (default, no extra round-trips) ---
client = TrackedAnthropicClient(
    api_key=API_KEY,
    log_path="logs/usage.jsonl",
    slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
    notify_desktop=False,
    auto_pre_check=False,  # explicit mode
)

# --- Option B: automatic pre-check on every create() ---
# client = TrackedAnthropicClient(
#     api_key=API_KEY,
#     log_path="logs/usage.jsonl",
#     slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
#     notify_desktop=False,
#     auto_pre_check=True,  # runs count_tokens before every create()
# )

print(f"Starting demo — {len(PROMPTS)} API calls")
print("Limits auto-detected from your subscription tier on the first call.\n")
print("─" * 60)

for i, prompt in enumerate(PROMPTS, 1):
    call_kwargs = dict(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    print(f"\nPrompt {i}: {prompt}")

    try:
        # Option A only: explicit pre-check before this call
        if not client.messages.auto_pre_check:
            client.messages.pre_check(**call_kwargs)

        response = client.messages.create(**call_kwargs)
        print(f"Response: {response.content[0].text.strip()}")

    except ExecutionHaltedError as e:
        print(f"\n[Skipped] {e}")
        break

print("\n" + "─" * 60)
client.tracker.print_summary()
client.tracker.log_to_file()
print(f"Session logged to: {os.path.abspath('logs/usage.jsonl')}")
