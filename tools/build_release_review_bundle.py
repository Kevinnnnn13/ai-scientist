"""Build and test a narrowly allowlisted, standard-library-only audit bundle."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "tools/release_review_assets"
STUDIES = {
    "v2": ROOT / "robustness_runs/programmatic_release_v2_dev_20261014",
    "v21": ROOT / "robustness_runs/programmatic_release_v21_dev_20261015",
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def segments(raw, functions, constants=()):
    text = raw.decode("utf-8-sig")
    selected, locations = [], {}
    for node in ast.parse(text).body:
        name = node.name if isinstance(node, ast.FunctionDef) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], "id", None)
        if name in set(functions) | set(constants):
            selected.append(ast.get_source_segment(text, node))
            locations[name] = [node.lineno, node.end_lineno]
    if set(locations) != set(functions) | set(constants):
        raise ValueError("frozen source does not contain all expected definitions")
    return "\n\n\n".join(selected) + "\n", locations


def build(output):
    archive = output.with_suffix(".zip")
    checksum = archive.with_suffix(".zip.sha256")
    if any(p.exists() for p in (output, archive, checksum)):
        raise FileExistsError("use a new bundle path; existing files are preserved")
    inventory = {}

    def add(relative, raw, provenance):
        if relative in inventory:
            raise ValueError("duplicate bundle path")
        if re.search(rb"\bsk-[A-Za-z0-9_-]{20,}|\bBearer\s+[A-Za-z0-9_.-]{20,}", raw):
            raise ValueError("possible credential in " + relative)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
        inventory[relative] = {"sha256": digest(raw), "bytes": len(raw), **provenance}

    def copy_file(source, relative):
        add(relative, source.read_bytes(), {"source": source.relative_to(ROOT).as_posix()})

    for name in ("README.md", "reproduce.py"):
        copy_file(ASSETS / name, name)
    copy_file(ROOT / "robustness_runs/pilot_6_v2_combined/per_run_metrics.csv",
              "data/historical_pilot/per_run_metrics.csv")
    for version, study in STUDIES.items():
        frozen = read(study / "manifest.json")
        with zipfile.ZipFile(study / "frozen_source.zip") as zipped:
            sources = (
                "src/selective_release.py", "src/programmatic_release_tasks.py",
                "src/anchor_checker.py", "tools/programmatic_release_oracle.py",
                "tools/programmatic_release_worker.py", "tools/run_programmatic_release.py",
            )
            for source in sources:
                raw = zipped.read(source)
                if digest(raw) != frozen["code"][source]:
                    raise ValueError("snapshot hash mismatch: " + source)
                destination = "code/" + version + "/" + Path(source).name
                copy_source = {"source": study.relative_to(ROOT).as_posix() +
                               "/frozen_source.zip!" + source}
                add(destination, raw, copy_source)
            for source, destination, functions, constants, header in (
                ("src/langgraph_agent.py", "legacy_release.py",
                 ("floor_for", "novelty_floor_for", "pass_check", "exploratory_check",
                  "assess_plan_release"), ("MAX_DATA_ROUNDS",),
                 "# Exact source segments; provenance is recorded in MANIFEST.json.\n\n"),
                ("tools/run_programmatic_release.py", "score_saved.py",
                 ("decision_usable", "score_result"), (),
                 "from programmatic_release_oracle import evaluate\n\n"),
            ):
                raw = zipped.read(source)
                if digest(raw) != frozen["code"][source]:
                    raise ValueError("snapshot hash mismatch: " + source)
                body, locations = segments(raw, functions, constants)
                add("code/" + version + "/" + destination, (header + body).encode("utf-8"),
                    {"source": study.relative_to(ROOT).as_posix() + "/frozen_source.zip!" + source,
                     "source_sha256": digest(raw), "extracted_definitions": locations})
        for name in ("manifest.json", "run_order.json", "private_environments.json"):
            copy_file(study / name, "data/" + version + "/" + name)
        for path in sorted((study / "inputs").glob("*.json")):
            copy_file(path, "data/" + version + "/inputs/" + path.name)
        if version == "v21":
            copy_file(study / "READINESS.json", "data/v21/READINESS.json")
            if any((study / name).exists() for name in ("runs", "attempts", "scored")):
                raise ValueError("v2.1 is no longer an unstarted study; revise bundle scope")
        else:
            for path in sorted((study / "scored").glob("*.json")):
                copy_file(path, "data/v2/scored/" + path.name)
            for parent in ("runs", "attempts"):
                for path in sorted((study / parent).rglob("*")):
                    if path.is_file() and path.name in ("result.json", "rounds.jsonl", "api_trace.jsonl"):
                        copy_file(path, "data/v2/" + path.relative_to(study).as_posix())
    for name in ("programmatic_release_protocol_v2_20261014.md",
                 "programmatic_release_v21_amendment_20261015.md",
                 "programmatic_release_execution_addendum_20261015.md"):
        copy_file(ROOT / "docs" / name, "protocols/" + name)
    copy_file(ROOT / "docs/submission_prep_20261015/Methods_controlled_release_draft.md",
              "protocols/Methods_controlled_release_draft.md")
    with (output / "MANIFEST.json").open("x", encoding="utf-8") as stream:
        json.dump({"bundle_version": "offline-review-20261015-v1",
                   "scope": "Saved v2 development replay and unstarted v2.1 materials",
                   "files": inventory}, stream, ensure_ascii=True, indent=2)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                zipped.write(path, output.name + "/" + path.relative_to(output).as_posix())
    with checksum.open("x", encoding="ascii") as stream:
        stream.write(digest(archive.read_bytes()) + "  " + archive.name + "\n")
    return archive


def self_test(archive):
    # All tests run on an isolated extraction; packaged/original data stay intact.
    with tempfile.TemporaryDirectory(prefix="release-offline-audit-") as temporary:
        temp = Path(temporary)
        with zipfile.ZipFile(archive) as zipped:
            for name in zipped.namelist():
                if temp.resolve() not in (temp / name).resolve().parents:
                    raise ValueError("unsafe archive member")
            zipped.extractall(temp)
        extracted = temp / archive.stem
        command = [sys.executable, "-B", "-I", str(extracted / "reproduce.py")]
        output = temp / "outcomes.json"
        success = subprocess.run(command + ["--output", str(output)], cwd=temp,
                                 capture_output=True, text=True, encoding="utf-8", timeout=60)
        if success.returncode:
            raise RuntimeError(success.stdout + success.stderr)
        result = read(output)
        target = extracted / "data/v2/inputs/u0001.json"
        original = target.read_bytes()
        target.write_bytes(original + b"\n")
        failure = subprocess.run(command, cwd=temp, capture_output=True,
                                 text=True, encoding="utf-8", timeout=60)
        if failure.returncode == 0 or "checksum mismatch" not in failure.stderr:
            raise RuntimeError("tampered input was not rejected")
        target.write_bytes(original)
        target.unlink()
        missing = subprocess.run(command, cwd=temp, capture_output=True,
                                 text=True, encoding="utf-8", timeout=60)
        if missing.returncode == 0 or "file inventory differs" not in missing.stderr:
            raise RuntimeError("missing input was not rejected")
        return {"status": "passed", "isolated_zip_replay": True,
                "tampered_input_rejected": True, "missing_input_rejected": True,
                "results": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    archive = build(output)
    if args.self_test:
        checks = self_test(archive)
        with archive.with_suffix(".verification.json").open("x", encoding="utf-8") as stream:
            json.dump(checks, stream, ensure_ascii=False, indent=2)
        print(json.dumps({"status": checks["status"], "bundle": str(archive),
                          "files": checks["results"]["files_verified"],
                          "tamper_test": True, "missing_file_test": True}, ensure_ascii=True))
    else:
        print(str(archive))


if __name__ == "__main__":
    main()
