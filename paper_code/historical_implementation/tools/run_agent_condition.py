# -*- coding: utf-8 -*-
"""Run one Agent condition with deterministic fault-injection hooks."""

import argparse
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import robustness_hooks


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--system", default=os.getenv("ROBUSTNESS_SYSTEM", "F0"))
    parser.add_argument("--robustness-config", default=os.getenv("ROBUSTNESS_CONFIG", ""))
    parser.add_argument("--quality", default="超好")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("question")
    args, extra = parser.parse_known_args()

    config = robustness_hooks.load_config(args.robustness_config or None)
    if args.dry_run:
        import json
        print(json.dumps({
            "system": args.system,
            "quality": args.quality,
            "question": args.question,
            "extra": extra,
            "config": config,
        }, ensure_ascii=False, indent=2))
        return 0
    robustness_hooks.apply_hooks(config)

    system = str(args.system or "F0").upper()
    if system.startswith("B1"):
        from flat_rag_baseline import run
        state = run(args.question, args.quality)
        return 0 if state.get("status") != "error" else 3

    # langgraph_agent.main() parses sys.argv itself.
    import langgraph_agent
    sys.argv = [sys.argv[0], args.question, "--quality", args.quality] + list(extra or [])
    try:
        langgraph_agent.main()
        return 0
    except SystemExit as exc:
        return int(exc.code or 0)


if __name__ == "__main__":
    sys.exit(main())
