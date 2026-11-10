"""One bounded DeepSeek connectivity probe, separate from research outcomes."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        raise FileExistsError("probe outputs must not be overwritten")
    os.environ["LLM_BACKEND"] = "deepseek"
    import llm_client
    factory = llm_client.get_client
    status = {
        "purpose": "connectivity_only_not_a_study_observation",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "backend": "deepseek", "requested_model": llm_client.active_model(),
    }

    def bounded_client():
        client, model = factory()
        client = client.with_options(timeout=35, max_retries=0)

        def create(**kwargs):
            kwargs["max_tokens"] = 32
            try:
                response = client.chat.completions.create(**kwargs)
                status.update(returned_model=response.model, api_status="received",
                              request_id=getattr(response, "_request_id", None))
                return response
            except Exception as exc:
                status.update(error_type=type(exc).__name__,
                              http_status=getattr(exc, "status_code", None),
                              request_id=getattr(exc, "request_id", None))
                raise

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), model

    llm_client.get_client = bounded_client
    start = time.monotonic()
    try:
        answer = llm_client.json_chat(
            'Return JSON {"ok":true}.', system="Return JSON only.",
            schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}},
                    "additionalProperties": False}, max_retries=0,
        )
        status["passed"] = answer == {"ok": True}
    except Exception:
        status["passed"] = False
    status.update(seconds=time.monotonic() - start, usage=llm_client.get_usage())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(status, stream, indent=2, ensure_ascii=True)
    print(json.dumps(status), flush=True)
    return 0 if status["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
