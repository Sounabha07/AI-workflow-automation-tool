"""Manual check: one real Gemini call through the LLM block. Not run in CI.

    GEMINI_API_KEY=... python scripts/try_gemini.py
    GEMINI_API_KEY=... python scripts/try_gemini.py --json
    GEMINI_API_KEY=... python scripts/try_gemini.py --model gemini-3.5-flash-lite "Your prompt"

Reads the key from the environment only and never prints it.
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from blocks.base import FatalError, RetryableError  # noqa: E402
from blocks.llm import LLMBlock  # noqa: E402

SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}, "country": {"type": "string"}},
    "required": ["city", "country"],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", nargs="?", default="In one sentence, what is a DAG?")
    ap.add_argument("--model", default=None)
    ap.add_argument("--json", action="store_true", help="JSON mode with a small city/country schema")
    args = ap.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        print("Set GEMINI_API_KEY in the environment first.", file=sys.stderr)
        return 2

    config = {"provider": "gemini", "prompt": args.prompt}
    if args.model:
        config["model"] = args.model
    if args.json:
        config.update(
            prompt="Name the capital of Japan.",
            response_format="json",
            json_schema=SCHEMA,
        )

    try:
        out = asyncio.run(LLMBlock().execute(config, {}))
    except (FatalError, RetryableError) as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
