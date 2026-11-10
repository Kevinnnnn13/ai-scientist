"""Recompute completed development/formal results from a portable evidence ZIP."""

from collections import Counter
import hashlib
import importlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def within(root, relative):
    path = (root / relative).resolve()
    require(root.resolve() in path.parents, "unsafe relative path")
    return path


def no_network(event, args):
    if event.startswith("socket."):
        raise RuntimeError("network is disabled")


def main():
    sys.addaudithook(no_network)
    inventory = read(ROOT / "MANIFEST.json")
    files = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()}
    require(files == set(inventory["files"]) | {"MANIFEST.json"}, "file inventory mismatch")
    for relative, expected in inventory["files"].items():
        require(digest(within(ROOT, relative)) == expected, "checksum mismatch: " + relative)
    sys.path.insert(0, str(ROOT / "code"))
    from selective_release import canonical_hash
    from score_saved import score_result
    from programmatic_release_oracle import evaluate
    outputs = {}
    for phase in ("development", "formal"):
        study = ROOT / "data" / phase
        manifest = read(study / "manifest.json")
        for relative, expected in manifest["inputs"].items():
            require(digest(within(study, relative)) == expected, "input freeze mismatch")
        require(digest(study / "run_order.json") == manifest["order_sha256"], "order mismatch")
        require(digest(study / "private_environments.json") == manifest["environment_sha256"],
                "environment mismatch")
        for source in ("src/selective_release.py", "src/programmatic_release_tasks.py",
                       "src/anchor_checker.py", "tools/programmatic_release_oracle.py"):
            require(digest(ROOT / "code" / Path(source).name) == manifest["code"][source],
                    "frozen source mismatch")
        order = read(study / "run_order.json")
        require(len(order) == manifest["planned_units"], "planned count mismatch")
        envs = read(study / "private_environments.json")
        groups, round_count, repairs, failures = {}, 0, 0, 0
        for row in order:
            score = read(study / "scored" / (row["unit_id"] + ".json"))
            resultfile = within(study, score["result_path"])
            require(digest(resultfile) == score["result_sha256"], "result checksum mismatch")
            result = read(resultfile)
            payload = read(study / "inputs" / (row["unit_id"] + ".json"))
            require(result["public_input_sha256"] == canonical_hash(payload), "input binding mismatch")
            require(all(score[k] == v for k, v in row.items()), "order/score mismatch")
            expected = score_result(result, envs[row["case_id"]])
            require(score["truth"] == expected["truth"] and score["arms"] == expected["arms"],
                    "recomputed outcome differs")
            failed = result["status"] != "completed" or any(
                not x["evaluation_valid"] for x in expected["arms"].values())
            failures += failed
            history = result.get("history", [])
            if history:
                truths = [evaluate(entry["artifact"], envs[row["case_id"]]) for entry in history]
                require(result["artifact"] == history[-1]["artifact"], "final/history mismatch")
                round_count += len(history)
                repairs += not truths[0]["eligible"] and truths[-1]["eligible"]
            for arm, data in expected["arms"].items():
                group = groups.setdefault(row["kind"] + ":" + arm, Counter())
                group["n"] += 1
                group["valid"] += data["evaluation_valid"]
                if data["evaluation_valid"]:
                    group["eligible"] += data["eligible"]
                    group["ineligible"] += not data["eligible"]
                    for key in ("released", "false_release", "false_rejection", "safe_withhold",
                                "released_task_success", "released_safe_narrowing"):
                        group[key] += data[key]
        saved = read(study / "summary.json")
        require({k: dict(v) for k, v in groups.items()} == saved["groups"],
                "recomputed groups differ")
        require(failures == saved["execution_failures"], "failure count mismatch")
        api, models, tokens = Counter(), Counter(), Counter()
        for tracefile in study.rglob("api_trace.jsonl"):
            for line in tracefile.read_text(encoding="utf-8").splitlines():
                trace = json.loads(line)
                api[trace["status"]] += 1
                response = trace.get("response", {})
                if response.get("model"):
                    models[response["model"]] += 1
                for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    tokens[name] += (response.get("usage") or {}).get(name, 0) or 0
        recorded = read(ROOT / "reports" / phase / "audit.json")
        require(dict(api) == recorded["api_events"] and
                dict(models) == recorded["response_models"] and
                dict(tokens) == recorded["recorded_tokens_all_traces"], "trace totals differ")
        outputs[phase] = {"planned_units": len(order), "execution_failures": failures,
                          "groups": groups, "generation_rounds_rescored": round_count,
                          "actual_repairs": repairs, "api_events": api,
                          "response_models": models, "recorded_tokens": tokens}
    print(json.dumps({"status": "passed", "files_verified": len(inventory["files"]),
                      "network": "disabled", "studies": outputs}, indent=2))


if __name__ == "__main__":
    main()
