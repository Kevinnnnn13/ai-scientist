"""Archive completed studies using an explicit data/source allowlist."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

from build_release_review_bundle import segments

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "tools/release_review_assets"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def checksum(raw):
    return hashlib.sha256(raw).hexdigest()


def archive(output):
    zip_path = output.with_suffix(".zip")
    require_new = (output, zip_path, zip_path.with_suffix(".zip.sha256"),
                   zip_path.with_suffix(".verification.json"))
    if any(p.exists() for p in require_new):
        raise FileExistsError("Use a new archive name.")
    files, provenance = {}, {}

    def add(name, raw):
        if name in files:
            raise ValueError("duplicate archive name")
        if re.search(rb"\bsk-[A-Za-z0-9_-]{20,}|\bBearer\s+[A-Za-z0-9_.-]{20,}", raw):
            raise ValueError("possible credential in " + name)
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
        files[name] = checksum(raw)

    add("README.md", (ASSETS / "COMPLETED_README.md").read_bytes())
    add("reproduce.py", (ASSETS / "reproduce_completed.py").read_bytes())
    previous_code = None
    for phase, suffix in (("development", "dev"), ("formal", "formal")):
        study = ROOT / ("robustness_runs/programmatic_release_v21_" + suffix + "_20261015")
        summary = read(study / "summary.json")
        if summary["completed_units"] != summary["planned_units"]:
            raise ValueError("study incomplete")
        manifest = read(study / "manifest.json")
        if previous_code is not None and manifest["code"] != previous_code:
            raise ValueError("development/formal code mismatch")
        previous_code = manifest["code"]
        for name in ("manifest.json", "run_order.json", "private_environments.json",
                     "execution_manifest.json", "summary.json"):
            add("data/" + phase + "/" + name, (study / name).read_bytes())
        for directory in ("inputs", "scored", "runs", "attempts", "execution_sessions"):
            for path in sorted((study / directory).rglob("*")):
                if path.is_file() and path.suffix in (".json", ".jsonl"):
                    add("data/" + phase + "/" + path.relative_to(study).as_posix(), path.read_bytes())
        if (study / "DEVELOPMENT_ACCEPTANCE.json").exists():
            add("data/" + phase + "/DEVELOPMENT_ACCEPTANCE.json",
                (study / "DEVELOPMENT_ACCEPTANCE.json").read_bytes())
        for kind in ("audit", "figures"):
            report = ROOT / ("robustness_runs/programmatic_release_v21_" + suffix +
                             "_" + kind + "_20261015")
            for path in sorted(report.iterdir()):
                if path.is_file() and path.suffix in (".json", ".csv", ".md", ".png", ".pdf", ".svg"):
                    add("reports/" + phase + "/" + path.name, path.read_bytes())
        if phase == "formal":
            with zipfile.ZipFile(study / "frozen_source.zip") as frozen:
                for source in ("src/selective_release.py", "src/programmatic_release_tasks.py",
                               "src/anchor_checker.py", "tools/programmatic_release_oracle.py",
                               "tools/programmatic_release_worker.py", "tools/run_programmatic_release.py"):
                    raw = frozen.read(source)
                    if checksum(raw) != manifest["code"][source]:
                        raise ValueError("frozen source mismatch")
                    destination = "code/" + Path(source).name
                    add(destination, raw)
                    provenance[destination] = {"source": source, "source_sha256": checksum(raw)}
                source = "tools/run_programmatic_release.py"
                raw = frozen.read(source)
                body, locations = segments(raw, ("decision_usable", "score_result"))
                add("code/score_saved.py",
                    ("from programmatic_release_oracle import evaluate\n\n" + body).encode("utf-8"))
                provenance["code/score_saved.py"] = {
                    "source": source, "source_sha256": checksum(raw), "definitions": locations}
    for source in ("tools/report_controlled_study.py", "tools/audit_saved_release_decisions.py",
                   "tools/plot_controlled_release_results.py"):
        add("analysis_source/" + Path(source).name, (ROOT / source).read_bytes())
    for name in ("programmatic_release_protocol_v2_20261014.md",
                 "programmatic_release_v21_amendment_20261015.md",
                 "programmatic_release_execution_addendum_20261015.md"):
        add("protocols/" + name, (ROOT / "docs" / name).read_bytes())
    add("SOURCE_PROVENANCE.json", json.dumps(provenance, indent=2).encode("utf-8"))
    with (output / "MANIFEST.json").open("x", encoding="utf-8") as stream:
        json.dump({"version": "completed-v21-20261015", "files": files}, stream, indent=2)
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                zipped.write(path, output.name + "/" + path.relative_to(output).as_posix())
    with zip_path.with_suffix(".zip.sha256").open("x", encoding="ascii") as stream:
        stream.write(checksum(zip_path.read_bytes()) + "  " + zip_path.name + "\n")
    with tempfile.TemporaryDirectory(prefix="completed-release-") as temporary:
        temp = Path(temporary)
        with zipfile.ZipFile(zip_path) as zipped:
            for name in zipped.namelist():
                if temp.resolve() not in (temp / name).resolve().parents:
                    raise ValueError("unsafe archive member")
            zipped.extractall(temp)
        script = temp / output.name / "reproduce.py"
        command = [sys.executable, "-B", "-I", "-S", str(script)]
        result = subprocess.run(command, cwd=temp, capture_output=True, text=True,
                                encoding="utf-8", timeout=60)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        replay = json.loads(result.stdout)
        changed = temp / output.name / "data/formal/inputs/u0001.json"
        changed.write_bytes(changed.read_bytes() + b"\n")
        rejected = subprocess.run(command, cwd=temp, capture_output=True, text=True,
                                  encoding="utf-8", timeout=60)
        if rejected.returncode == 0 or "checksum mismatch" not in rejected.stderr:
            raise RuntimeError("tamper test failed")
    with zip_path.with_suffix(".verification.json").open("x", encoding="utf-8") as stream:
        json.dump({"isolated_zip_replay": replay, "tampered_input_rejected": True},
                  stream, indent=2)
    print(json.dumps({"archive": str(zip_path), "status": replay["status"],
                      "files_verified": replay["files_verified"],
                      "tampered_input_rejected": True}, ensure_ascii=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    archive(Path(args.output).resolve())


if __name__ == "__main__":
    main()
