"""Verify delivered file hashes, manuscript assets and historical evidence offline."""

from collections import Counter
import argparse
import csv
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-manifest", action="store_true")
    args = parser.parse_args()
    verified = 0
    if not args.before_manifest:
        inventory = read(ROOT / "MANIFEST.json")["files"]
        actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()}
        assert actual == set(inventory) | {"MANIFEST.json"}, "Inventory mismatch"
        for relative, item in inventory.items():
            target = (ROOT / relative).resolve()
            assert ROOT in target.parents
            assert digest(target) == item["sha256"], relative
        verified = len(inventory)
    qa = read(ROOT / "05_provenance/document_QA_original.json")
    for original, stem in zip(qa["documents"], ("Manuscript", "Supplementary_Information")):
        assert digest(ROOT / "01_paper" / (stem + ".docx")) == original["sha256"]
        assert digest(ROOT / "01_paper" / (stem + ".pdf")) == original["pdf_sha256"]
    embedded = {}
    for stem, folder, prefix, count in (
        ("Manuscript", "main", "Fig", 3),
        ("Supplementary_Information", "supplement", "SuppFig", 4),
    ):
        with ZipFile(ROOT / "01_paper" / (stem + ".docx")) as zipped:
            hashes = Counter(hashlib.sha256(zipped.read(n)).hexdigest()
                             for n in zipped.namelist() if n.startswith("word/media/"))
        expected = Counter(digest(ROOT / "02_figures" / folder / f"{prefix}{i}.png")
                           for i in range(1, count + 1))
        assert hashes == expected, stem
        embedded[stem] = count

    historical = ROOT / "03_data/historical"
    pilot = rows(historical / "pilot72/per_run_metrics.csv")
    assert len(pilot) == 72 and len({(r["question_id"], r["condition_id"]) for r in pilot}) == 72
    totals = Counter()
    for row in pilot:
        base = historical / "pilot72" / row["question_id"] / row["condition_id"]
        state, result = read(base / "state.json"), read(base / "result.json")
        assert result["run_id"] == row["run_id"]
        assert state.get("plan_status") == result.get("plan_status") == row["plan_status"]
        assert result["exit_code"] == 0 and result["ok"] and not result["timed_out"]
        totals[row["plan_status"]] += 1
    assert totals == {"in_progress": 53, "validated": 13, "ungated": 6}
    guard_results = list((historical / "guard6/raw_runs").rglob("result.json"))
    assert len(guard_results) == 6
    guard_states = []
    for resultfile in guard_results:
        states = list(resultfile.parent.rglob("state.json"))
        assert len(states) == 1
        state = read(states[0])
        assert state["plan_status"] == "in_progress"
        assert read(resultfile)["exit_code"] != 0
        guard_states.append(state)
    claims = rows(historical / "claim_audit/analysis_focused_rereview/final/adjudicated_claims.csv")
    assert len(claims) == 63
    plot = read(ROOT / "04_code/supplement_figures/data/figure_data.json")
    assert plot["pilot"] == pilot
    assert len(plot["repair_pairs"]) == 6
    for row in plot["repair_pairs"]:
        prior = read(historical / "pilot72" / row["question_id"] / "F0_judge_override/state.json")
        followup = next(state for state in guard_states
                        if state.get("question") == prior.get("question"))
        assert prior["plan_status"] == row["before_status"] == "validated"
        assert followup["plan_status"] == row["after_status"] == "in_progress"
        assert prior["best_score"] == row["before_score"] == row["after_score"] == followup["best_score"]
        assert prior["best_data_score"] == row["before_data_score"] == row["after_data_score"] == followup["best_data_score"]
    usage = read(ROOT / "03_data/m2_m5/M2_usage_audit.json")
    token_totals = Counter()
    for entry in usage["per_run_trace_bindings"]:
        base = ROOT / "03_data/cd_fairness/data/supplement/runs" / entry["run"]
        assert digest(base / "result.json") == entry["result_sha256"]
        assert digest(base / "api_trace.jsonl") == entry["trace_sha256"]
        events = [json.loads(line) for line in (base / "api_trace.jsonl").read_text(encoding="utf-8").splitlines()]
        token_totals[entry["run"].rsplit("_", 1)[1]] += sum(
            (e.get("response", {}).get("usage") or {}).get("total_tokens", 0) for e in events)
    assert token_totals == {"C": 67118, "D": 38125}
    print(json.dumps({"status": "passed", "files_verified": verified,
                      "document_hashes_match_original_QA": True,
                      "embedded_figures": embedded, "historical_pilot_states": dict(totals),
                      "historical_guard_runs": 6, "historical_adjudicated_claims": len(claims),
                      "M2_tokens": dict(token_totals), "model_calls": 0}, indent=2))


if __name__ == "__main__":
    main()
