import os
from typing import Optional


def resolve_api_key(api_key: Optional[str] = None) -> Optional[str]:
    """
    Resolve an Anthropic API key from multiple sources, in priority order:
      1. Explicit api_key argument
      2. ANTHROPIC_API_KEY environment variable
      3. None (let the SDK raise its own auth error)

    If no key is found and the code is running inside Claude Code (detected via
    the CLAUDECODE env var), a targeted message is printed to explain that
    claude.ai Pro and Anthropic API access are separate products.
    """
    # 1. Explicit argument
    if api_key:
        return api_key

    # 2. Environment variable (also what the SDK reads automatically)
    from_env = os.environ.get("ANTHROPIC_API_KEY")
    if from_env:
        return from_env

    # 3. No key found — print a context-aware error before returning None
    in_claude_code = os.environ.get("CLAUDECODE") == "1"

    if in_claude_code:
        print(
            "\n[Auth] No ANTHROPIC_API_KEY found.\n"
            "You are running inside Claude Code, but claude.ai Pro and Anthropic API\n"
            "access are separate products with separate billing.\n\n"
            "To use this tracker you need an Anthropic API key:\n"
            "  1. Go to https://console.anthropic.com/settings/keys\n"
            "  2. Create a key and copy it\n"
            "  3. Set it in your shell:  export ANTHROPIC_API_KEY=sk-ant-...\n"
            "     or pass it directly:  TrackedAnthropicClient(api_key='sk-ant-...')\n"
        )
    else:
        print(
            "\n[Auth] No ANTHROPIC_API_KEY found.\n"
            "  1. Sign up at https://console.anthropic.com\n"
            "  2. Create an API key under Settings → API Keys\n"
            "  3. Set it in your shell:  export ANTHROPIC_API_KEY=sk-ant-...\n"
            "     or pass it directly:  TrackedAnthropicClient(api_key='sk-ant-...')\n"
        )

    return None


def is_claude_code() -> bool:
    """Return True when the process is running inside a Claude Code session."""
    return os.environ.get("CLAUDECODE") == "1"
