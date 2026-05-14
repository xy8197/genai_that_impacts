# Claude API Token Usage Tracker

A drop-in wrapper around the Anthropic Python SDK that automatically tracks token usage and cost across your session — with proactive warnings, a hard halt at 95%, and optional pre-call estimation to avoid rate-limit surprises..

---

## Who this is for

This project supports two user types with different entry points:

| | Claude Pro / Claude Code user | Anthropic API user |
|---|---|---|
| **API key needed?** | No | Yes |
| **Charged per token?** | No (flat fee) | Yes |
| **Use case** | Estimate what prompts would cost before adopting the API | Track live usage, enforce cost limits, halt at 95% |
| **Entry point** | `TokenEstimator` + `examples/estimate_demo.py` | `TrackedAnthropicClient` + `examples/track_usage_demo.py` |

### Claude Pro / Claude Code users
Use `TokenEstimator` to estimate token counts and costs **locally — no API key required**. Useful for sizing prompts, understanding how API billing works, and deciding whether to adopt API access.

```python
from utils import TokenEstimator

estimator = TokenEstimator(model="claude-sonnet-4-6")
result = estimator.estimate(
    messages=[{"role": "user", "content": "Explain RAG in one sentence."}],
    max_tokens=200,
)
estimator.print_estimate(result)
```

Run the Pro user demo:
```bash
python3 examples/estimate_demo.py
```

### Anthropic API users
Use `TrackedAnthropicClient` to track live usage, enforce token/cost limits, and receive warnings as you approach your rate-limit ceiling. Requires `ANTHROPIC_API_KEY`.

```python
from utils import TrackedAnthropicClient

client = TrackedAnthropicClient(log_path="logs/usage.jsonl")
response = client.messages.create(model="claude-sonnet-4-6", ...)
client.tracker.print_summary()
```

Run the API user demo:
```bash
python3 examples/track_usage_demo.py
```

## Why this exists

When building with Claude via the API, it's easy to lose track of how many tokens you're consuming — especially across multi-step workflows. This tool gives you visibility into usage in real time, warns you before you hit limits, and stops new executions cleanly when you're close to your rate-limit ceiling.

---

## How it works

- **Auto-detects limits** from your Anthropic subscription tier via rate-limit response headers — no manual setup needed
- **Tracks every API call** automatically (input tokens, output tokens, cache tokens, estimated cost)
- **Warns at 80% and 90%** of either the token or cost limit — advisory, execution continues
- **Halts at 95%** — the triggering call completes fully, then no new calls are allowed
- **Pre-call estimation** — optionally checks if a call will exceed your remaining rate-limit window *before* executing it, using the `count_tokens` API (no charge)
- **Notifies** via Slack webhook and/or desktop notification
- **Logs** every session summary to a `.jsonl` file

---

## Authentication

This tracker calls the **Anthropic API**, which requires an API key — separate from a claude.ai Pro or Claude Code subscription.

| Scenario | What to do |
|---|---|
| **API key user** | Set `ANTHROPIC_API_KEY=sk-ant-...` in your shell, or pass `api_key=` to `TrackedAnthropicClient` |
| **Claude Code / Pro user** | claude.ai Pro gives you access to Claude Code (the CLI), but **not** the Anthropic API. You still need a separate API key from [console.anthropic.com](https://console.anthropic.com/settings/keys) |

The client resolves your key automatically in this order:
1. Explicit `api_key=` argument passed to `TrackedAnthropicClient`
2. `ANTHROPIC_API_KEY` environment variable

If no key is found, a context-aware message is printed. If you are running inside Claude Code, the message will explain the Pro vs API distinction specifically.

```bash
# Set once in your shell profile (~/.zshrc or ~/.bashrc)
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Requirements

| Requirement | Minimum version | Notes |
|---|---|---|
| Python | 3.9+ | Python 3.7 and 3.8 are end-of-life and cannot install the `anthropic` SDK's compiled dependencies |
| pip | 21+ | Older pip versions cannot parse the `pyproject.toml` format used by modern packages |

## Installation

**1. Clone the repo**

```bash
git clone https://github.com/your-org/genai_that_impacts.git
cd genai_that_impacts/claude-api-token-usage
```

**2. Set up a Python 3.9+ environment**

If you are using Anaconda (or have Python 3.7/3.8 as your default), create a fresh environment first:

```bash
conda create -n claude-tracker python=3.9
conda activate claude-tracker
```

If you are using plain Python and already have 3.9+, a virtual environment is recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

You can verify your Python version before continuing:

```bash
python3 --version   # should show Python 3.9.x or higher
```

> **`python` vs `python3`** — On many systems (especially macOS and Linux), `python` points to Python 2 and `python3` points to Python 3. Use `python3` and `pip3` throughout this guide unless you have confirmed that `python` maps to Python 3 in your environment.

**3. Upgrade pip**

```bash
pip3 install --upgrade pip
```

**4. Install dependencies**

```bash
pip3 install -r requirements.txt
```

**5. Set your API key and optional Slack webhook**

```bash
export ANTHROPIC_API_KEY=sk-ant-...                          # required — see Authentication above
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/... # optional
```

---

## Usage

Replace `anthropic.Anthropic()` with `TrackedAnthropicClient()` — everything else stays the same.

```python
from utils import TrackedAnthropicClient, ExecutionHaltedError

client = TrackedAnthropicClient(
    log_path="logs/usage.jsonl",
    slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
)

try:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{"role": "user", "content": "Explain RAG in one sentence."}],
    )
    print(response.content[0].text)
except ExecutionHaltedError as e:
    print(f"Stopped: {e}")

client.tracker.print_summary()
client.tracker.log_to_file()
```

### Configuration options

All parameters are passed to `TrackedAnthropicClient()` when you create the client. You can find and edit them in [examples/track_usage_demo.py](examples/track_usage_demo.py), or set them directly in your own code.

```python
client = TrackedAnthropicClient(
    # --- Limits (auto-detected if omitted) ---
    token_limit=80_000,          # remove to auto-detect from your subscription tier
    cost_limit=0.72,             # remove to auto-detect from token_limit × model rate

    # --- Pre-call estimation ---
    auto_pre_check=False,        # set True to check every call automatically (see below)

    # --- Logging ---
    log_path="logs/usage.jsonl", # set to None to disable file logging

    # --- Notifications (both optional) ---
    slack_webhook_url="https://hooks.slack.com/services/...",  # or os.getenv("SLACK_WEBHOOK_URL")
    notify_desktop=False,        # set True to enable system pop-up alerts
)
```

| Parameter | Type | Default | What it does |
|---|---|---|---|
| `token_limit` | `int` | auto-detected | Max total tokens (input + output) before warnings and halt trigger. Auto-detected from your subscription's rate-limit header on the first API call. Override when you want a tighter per-session budget. |
| `cost_limit` | `float` | auto-detected | Max USD spend before warnings and halt trigger. Auto-detected as `token_limit × blended model rate`. Override with a fixed dollar amount, e.g. `cost_limit=0.50`. |
| `auto_pre_check` | `bool` | `False` | When `True`, calls the `count_tokens` API before every `create()` to warn if the call may exceed your remaining rate-limit window. Adds one extra API round-trip per call. Set to `False` and use `client.messages.pre_check()` instead for selective control. |
| `log_path` | `str` | `None` | File path where session summaries are appended as JSON lines after each `log_to_file()` call. The directory is created automatically if it doesn't exist. |
| `slack_webhook_url` | `str` | `None` | Slack [incoming webhook URL](https://api.slack.com/messaging/webhooks). When set, warnings and halt alerts are posted to your Slack channel. Use `os.getenv("SLACK_WEBHOOK_URL")` to avoid hardcoding credentials. |
| `notify_desktop` | `bool` | `False` | When `True`, sends a system pop-up notification (macOS, Windows, Linux) via `plyer` for every warning and halt event. |

### Pre-call estimation

Two options — choose based on your needs:

**Option A — Explicit `pre_check()` (recommended)**
Call it manually only where needed. Zero overhead on other calls.

```python
client = TrackedAnthropicClient(auto_pre_check=False)

estimate = client.messages.pre_check(
    model="claude-sonnet-4-6",
    messages=[{"role": "user", "content": "..."}],
    max_tokens=500,
)
# estimate = {"estimated_total": 720, "tokens_remaining": 800, "will_likely_exceed": False, ...}

response = client.messages.create(...)
```

**Option B — Automatic pre-check**
Runs `count_tokens` before every `create()`. Adds one extra API round-trip per call.

```python
client = TrackedAnthropicClient(auto_pre_check=True)

response = client.messages.create(...)  # pre_check runs automatically
```

---

## Run the demo

Choose the demo that matches your subscription type:

---

### I have a Claude Pro / Claude Code subscription (no API key)

No setup needed beyond installation. Run:

```bash
python3 examples/estimate_demo.py
```

This estimates token counts and costs locally — no API call is made.

---

### I have an Anthropic API key

Make sure your key is exported first:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Then run:

```bash
python3 examples/track_usage_demo.py
```

This makes live API calls, tracks usage in real time, and halts at 95% of your limit.

To switch between explicit and automatic pre-check, edit the `auto_pre_check` parameter in the `TrackedAnthropicClient(...)` block inside the demo file.

---

> **`python` not found?** Try `python3` instead. On macOS and Linux, `python` often points to Python 2. If `python3` is also not found, check that your conda environment is activated (`conda activate claude-tracker`) or your virtual environment is active (`source .venv/bin/activate`).

---

## Sample output

### Per-call console output

```
[Tracker] Limits auto-detected from API headers — Token limit: 80,000 tokens/min | Cost ceiling: $0.7200 (blended claude-sonnet-4-6 rate)

Prompt 1: What is prompt caching in LLMs? Answer in one sentence.
[Call 1] Tokens: 28 in / 32 out | Cost: $0.0006 | Total: 60 (0.1%)
Response: Prompt caching stores reusable parts of a prompt so they don't need to be re-processed on every call, reducing latency and cost.

Prompt 2: What is the difference between tokens and words? One sentence.
[Call 2] Tokens: 26 in / 28 out | Cost: $0.0010 | Total: 114 (0.1%)
Response: Tokens are sub-word units a model uses internally; a single word can be one or several tokens depending on its length and frequency.

...

⚠️  WARNING: Token usage at 80.0% of limit (64,100 / 80,000 tokens).
   → Slack notified

⚠️  WARNING: Token usage at 90.0% of limit (72,300 / 80,000 tokens).
   → Slack notified

⚠️  HALT: tokens at 96.2% (76,950 / 80,000). Current execution completed.
    No new executions will be run.
   → Slack notified
```

### Pre-check warning (Option A or B)

```
⚠️  PRE-CHECK WARNING: Estimated call (~1,450 tokens) exceeds remaining window budget
    (800 tokens remaining, resets at 2026-05-13T20:01:00Z). This call may be rate-limited.
```

### Session summary table

```
╔════════════════════════════════════════════════╗
║             Token Usage Summary                ║
╠════════════════════════════════════════════════╣
║  Model          : claude-sonnet-4-6            ║
║  Limit Source   : auto                         ║
║  API Calls      : 5                            ║
║  Input Tokens   : 62,400                       ║
║  Output Tokens  : 14,550                       ║
║  Cache Write    : 0                            ║
║  Cache Read     : 0                            ║
║  Total Tokens   : 76,950  (96.2% of 80,000)   ║
║  Estimated $    : $0.4057  (56.3% of $0.7200) ║
║  Status         : HALTED (tokens at 96.2%)     ║
╚════════════════════════════════════════════════╝
```

### JSON log line (`logs/usage.jsonl`)

```json
{
  "timestamp": "2026-05-13T20:00:42Z",
  "model": "claude-sonnet-4-6",
  "calls": 5,
  "input_tokens": 62400,
  "output_tokens": 14550,
  "cache_write_tokens": 0,
  "cache_read_tokens": 0,
  "total_tokens": 76950,
  "estimated_cost_usd": 0.4057,
  "token_limit": 80000,
  "cost_limit": 0.72,
  "limit_source": "auto",
  "halted": true,
  "halt_reason": "tokens at 96.2% (76,950 / 80,000)"
}
```

---

## Project structure

```
claude-api-token-usage/
  utils/
    __init__.py
    auth.py               # API key resolver, Claude Code detection
    estimator.py          # TokenEstimator — local estimation, no API key needed (Pro users)
    token_tracker.py      # TokenUsageTracker, ExecutionHaltedError, PRICING
    tracked_client.py     # TrackedAnthropicClient — live tracking (API users)
  examples/
    estimate_demo.py      # Pro / Claude Code users — no API key required
    track_usage_demo.py   # API users — live tracking with warnings and halt
  requirements.txt
  README.md
```

---

## Supported models

| Model | Input | Output | Cache Write | Cache Read |
|---|---|---|---|---|
| `claude-sonnet-4-6` | $3.00 / M | $15.00 / M | $3.75 / M | $0.30 / M |
| `claude-opus-4-7` | $15.00 / M | $75.00 / M | $3.75 / M | $0.30 / M |
| `claude-haiku-4-5-20251001` | $0.80 / M | $4.00 / M | $1.00 / M | $0.08 / M |

Pricing is used to derive the auto-detected cost ceiling and estimate costs in the session summary.
