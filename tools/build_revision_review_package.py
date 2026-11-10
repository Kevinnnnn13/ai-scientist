"""Package only selected evidence and manuscript artifacts, then test replay."""

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
DOCS = ROOT / "docs/manuscript_revision_20261015"
RUNS = ROOT / "robustness_runs"
OUTPUT = RUNS / "manuscript_revision_review_20261015.zip"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    if OUTPUT.exists():
        raise FileExistsError("preserve existing archive")
    files, provenance = {}, {}
    def add(name, raw):
        if name in files:
            raise ValueError("duplicate name")
        if re.search(rb"\bsk-[A-Za-z0-9_-]{20,}|\bBearer\s+[A-Za-z0-9_.-]{20,}", raw):
            raise ValueError("possible credential: " + name)
        files[name] = raw
    add("README.md", (DOCS / "MINIMUM_DATASET.md").read_bytes())
    add("reproduce.py", (DOCS / "reproduce_revision.py").read_bytes())
    add("original/controlled_release_v21_completed_20261015.zip",
        (RUNS / "controlled_release_v21_completed_20261015.zip").read_bytes())
    study = RUNS / "release_supplement_cd_20261015"
    for name in ("manifest.json","pairs.json","private_environments.json","summary.json"):
        add("data/supplement/" + name, (study / name).read_bytes())
    for folder in ("inputs","runs","scored"):
        for path in sorted((study / folder).rglob("*")):
            if path.is_file() and path.suffix in (".json",".jsonl"):
                add("data/supplement/" + path.relative_to(study).as_posix(), path.read_bytes())
    add("data/fairness.json", (RUNS / "release_fairness_20261015/fairness.json").read_bytes())
    add("historical/per_run_metrics.csv", (RUNS / "pilot_6_v2_combined/per_run_metrics.csv").read_bytes())
    add("protocol/release_supplement_protocol_20261015.md",
        (ROOT / "docs/release_supplement_protocol_20261015.md").read_bytes())
    for path in sorted((DOCS / "figures").iterdir()):
        if path.suffix in (".png",".pdf",".svg",".json"):
            add("figures/" + path.name, path.read_bytes())
    for name in ("manuscript_revised_20261015.docx","supplementary_information_20261015.docx",
                 "manuscript.md","supplement.md","REVISION_NOTES.md","build_manifest.json"):
        add("manuscript/" + name, (DOCS / name).read_bytes())
    for name in ("release_supplement_worker.py","run_release_supplement.py","release_fairness_check.py"):
        add("analysis_source/" + name, (ROOT / "tools" / name).read_bytes())
    add("analysis_source/build_documents.py", (DOCS / "build_documents.py").read_bytes())
    add("analysis_source/test_release_supplement.py", (ROOT / "tests/test_release_supplement.py").read_bytes())
    formal = RUNS / "programmatic_release_v21_formal_20261015"
    manifest = json.loads((formal / "manifest.json").read_text())
    with zipfile.ZipFile(formal / "frozen_source.zip") as zipped:
        for name in ("src/selective_release.py","src/programmatic_release_tasks.py",
                     "src/anchor_checker.py","tools/programmatic_release_oracle.py"):
            raw = zipped.read(name)
            if sha(raw) != manifest["code"][name]:
                raise ValueError("original code mismatch")
            destination = "code/" + Path(name).name
            add(destination, raw)
            provenance[destination] = {"source":name,"sha256":sha(raw)}
        raw = zipped.read("src/langgraph_agent.py")
        body, definitions = segments(raw, ("floor_for","novelty_floor_for","pass_check",
                                          "exploratory_check","assess_plan_release"), ("MAX_DATA_ROUNDS",))
        add("code/legacy_release.py", body.encode("utf-8"))
        provenance["code/legacy_release.py"] = {
            "source":"src/langgraph_agent.py","source_sha256":sha(raw),"definitions":definitions}
    add("SOURCE_PROVENANCE.json", json.dumps(provenance, indent=2).encode("utf-8"))
    add("MANIFEST.json", json.dumps({"version":"revision-review-20261015",
                                    "files":{name:sha(raw) for name,raw in files.items()}}, indent=2).encode("utf-8"))
    with zipfile.ZipFile(OUTPUT, "x", zipfile.ZIP_DEFLATED) as zipped:
        for name, raw in files.items():
            zipped.writestr(name, raw)
    with tempfile.TemporaryDirectory(prefix="revision-review-") as temp_name:
        temp = Path(temp_name)
        with zipfile.ZipFile(OUTPUT) as zipped:
            zipped.extractall(temp)
        command = [sys.executable,"-B","-I","-S",str(temp / "reproduce.py")]
        result = subprocess.run(command, cwd=temp, capture_output=True, encoding="utf-8", timeout=90)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        verified = json.loads(result.stdout)
        tamper = temp / "data/supplement/inputs/p001_C.json"
        tamper.write_bytes(tamper.read_bytes() + b"\n")
        result = subprocess.run(command, cwd=temp, capture_output=True, encoding="utf-8", timeout=90)
        if result.returncode == 0 or "checksum mismatch" not in result.stderr:
            raise RuntimeError("tamper rejection failed")
    checksum = sha(OUTPUT.read_bytes())
    OUTPUT.with_suffix(".verification.json").write_text(json.dumps({
        "replay":verified,"tamper_rejected":True,"sha256":checksum,
    }, indent=2), encoding="utf-8")
    OUTPUT.with_suffix(".zip.sha256").write_text(checksum + "  " + OUTPUT.name + "\n", encoding="ascii")
    print(json.dumps({"archive":str(OUTPUT),"sha256":checksum,"verified":verified}, indent=2))


if __name__ == "__main__":
    main()
