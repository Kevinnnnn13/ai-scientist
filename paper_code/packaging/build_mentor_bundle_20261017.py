"""Assemble and verify the current-paper mentor package; never call a model."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "docs/mentor_bundle_build_20261017"
DEST = ROOT / "docs/Paper_20261017"
OLD = Path.home() / "Documents/Codex/2026-09-17/wo"
CURRENT = ROOT / "docs/manuscript_integrated_20261017"
ARCHIVE = ROOT / "docs/论文导师审阅完整包_20261017.zip"
SOURCES = {
    "original": (ROOT / "robustness_runs/controlled_release_v21_completed_20261015.zip",
                 "56f10121d14750518de9fa7fa70cdd9b9456a2ac8744ed289e6a1ec44823606f"),
    "revision": (ROOT / "robustness_runs/manuscript_revision_review_20261015.zip",
                 "e644d352d6c601e90f3bb14aa534f755ca564ca6c60c42f85254c1f97578dc6b"),
    "m3": (ROOT / "docs/M3离线实验报告与复现包_20261016.zip",
           "960caf4bfadc45a3e7edf2951dbb2c474af2eee235e6a7b07d64eb87b5c9605d"),
    "history": (OLD / "AI_Scientist_advisor_review_20261014.zip",
                "26ad5bf82d0ef434b67de580c2af3827291e04bc2189700179d46423e07b88a3"),
    "early": (OLD / "audit_data_and_code_20260930.zip",
              "f09d6d5d63913113315c52c7d09a6489cf62dad79a073d571a1dd0ddb3570b47"),
}
COPIED = []


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def put(relative, raw, source):
    path = (DEST / relative).resolve()
    if DEST.resolve() not in path.parents:
        raise ValueError("Unsafe destination: " + relative)
    helpers = {"04_code/reproduce_figures.py", "04_code/verify_package.py",
               "04_code/packaging/build_mentor_bundle_20261017.py", "00_导师先读.md"}
    if path.exists() and path.read_bytes() != raw and relative not in helpers:
        raise ValueError("Existing evidence differs: " + relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or relative in helpers:
        path.write_bytes(raw)
    assert digest(path.read_bytes()) == digest(raw)
    COPIED.append({"path": relative, "source": source, "sha256": digest(raw), "bytes": len(raw)})


def copy(source, relative):
    put(relative, source.read_bytes(), str(source))


def extract(zipped, source, target, prefix="", select=None):
    count = 0
    for member in zipped.infolist():
        if member.is_dir() or not member.filename.startswith(prefix):
            continue
        name = member.filename[len(prefix):]
        if select and not select(name):
            continue
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts or ":" in name or "\\" in name:
            raise ValueError("Unsafe archive member")
        if target == "03_data/historical/guard6" and name.startswith("raw_runs/"):
            parts = list(pure.parts)
            parts[1] = parts[1].rsplit("_", 1)[1]
            if len(parts) > 3 and parts[2] == "runs":
                parts[2:4] = ["run"]
            name = "/".join(parts)
        put(target + "/" + name, zipped.read(member), source + "::" + member.filename)
        count += 1
    return count


def prepare():
    if (DEST / "MANIFEST.json").exists() or ARCHIVE.exists():
        raise FileExistsError("A delivery already exists; preserve it.")
    for label, (path, expected) in SOURCES.items():
        assert digest(path.read_bytes()) == expected, label
        with ZipFile(path) as zipped:
            assert zipped.testzip() is None, label
    DEST.mkdir(exist_ok=True)
    for source, target in (
        ("manuscript_integrated_M3_M5_20261017.docx", "Manuscript.docx"),
        ("qa/manuscript.pdf", "Manuscript.pdf"),
        ("supplementary_information_M3_M5_20261017.docx", "Supplementary_Information.docx"),
        ("qa/supplement.pdf", "Supplementary_Information.pdf"),
    ):
        copy(CURRENT / source, "01_paper/" + target)
    copy(CURRENT / "QA_VERIFICATION.json", "05_provenance/document_QA_original.json")
    copy(CURRENT / "build_manifest.json", "05_provenance/manuscript_build_manifest_original.json")
    copy(BUILD / "README_导师先读.md", "00_导师先读.md")
    for name in ("reproduce_figures.py", "verify_package.py"):
        copy(BUILD / name, "04_code/" + name)
    copy(Path(__file__), "04_code/packaging/build_mentor_bundle_20261017.py")

    counts = {}
    with ZipFile(SOURCES["original"][0]) as zipped:
        counts["original_v21"] = extract(zipped, "original", "03_data/original_v21",
                                          "controlled_release_v21_completed_20261015/")
    with ZipFile(SOURCES["revision"][0]) as zipped:
        counts["cd_fairness"] = extract(zipped, "revision", "03_data/cd_fairness")
    with ZipFile(SOURCES["m3"][0]) as zipped:
        counts["m3"] = extract(zipped, "m3", "03_data/m3")

    figure_stems = ["figure1_evidence_workflow_v3", "figure2_core_mechanisms",
                   "figure3_real_run_case", "figure4_faults_and_repair"]
    with ZipFile(SOURCES["history"][0]) as zipped:
        for old, new in (("evidence/pilot/", "pilot72"),
                         ("evidence/audit_provenance/", "audit_provenance"),
                         ("evidence/controlled_review/", "controlled_review")):
            counts[new] = extract(zipped, "history", "03_data/historical/" + new, old)
        extract(zipped, "history", "04_code/historical_implementation", "implementation_snapshot/",
                lambda n: n != "analysis/analyze_questionnaire.py")
        extract(zipped, "history", "04_code/supplement_figures", "figure_code/",
                lambda n: not n.startswith("output/") and not n.endswith(".png"))
        for i, stem in enumerate(figure_stems, 1):
            for ext in ("png", "pdf", "svg"):
                member = ("figure_code/output/svg/" if ext == "svg" else "figures/") + stem + "." + ext
                put(f"02_figures/supplement/SuppFig{i}.{ext}", zipped.read(member), "history::" + member)
        for name in ("included_source_files.json", "supplemental_sources.json", "evidence_verification.json"):
            put("05_provenance/historical_" + name, zipped.read("audit/" + name), "history::audit/" + name)
    with ZipFile(SOURCES["early"][0]) as zipped:
        counts["guard6"] = extract(zipped, "early", "03_data/historical/guard6",
                                     "delivery_stage_20260930_v2/repair_experiment/")
        extract(zipped, "early", "04_code/historical_guard", "delivery_stage_20260930_v2/code/")
        nested = "delivery_stage_20260930_v2/frozen_packet/pilot_6_v2_audit_packet_20260929_final.zip"
        raw = zipped.read(nested)
        with ZipFile(io.BytesIO(raw)) as claims:
            assert claims.testzip() is None
            counts["claim_audit"] = extract(claims, "early::" + nested, "03_data/historical/claim_audit")
    for i in range(1, 4):
        for ext in ("png", "pdf", "svg"):
            copy(ROOT / "docs/manuscript_revision_20261015/figures" / f"fig{i}.{ext}",
                 f"02_figures/main/Fig{i}.{ext}")
    copy(ROOT / "docs/manuscript_revision_20261015/build_documents.py",
         "04_code/main_figures/build_documents_original.py")
    inputs = {
        "formal": "robustness_runs/programmatic_release_v21_formal_figures_20261015/summary.json",
        "supp": "robustness_runs/release_supplement_cd_20261015/summary.json",
        "fair": "robustness_runs/release_fairness_20261015/fairness.json",
        "audit": "robustness_runs/programmatic_release_v21_formal_audit_20261015/audit.json",
    }
    for name, source in inputs.items():
        copy(ROOT / source, "04_code/main_figures/inputs/" + name + ".json")
    for name in ("integrate.py", "revision_content.py", "supplement_content.py", "related_work.py",
                 "related_work_sources.json", "manuscript.md", "supplement.md", "REVISION_NOTES.md"):
        copy(CURRENT / name, "04_code/manuscript_build/" + name)
    for name in ("M2_usage_audit.json", "literature.json", "build_update.py"):
        copy(ROOT / "docs/m2_m5_20261016" / name, "03_data/m2_m5/" + name)
    requirements = (DEST / "04_code/supplement_figures/requirements.txt").read_bytes()
    put("04_code/requirements_figures.txt", requirements, "recorded original plotting runtime")
    dump(DEST / "05_provenance/SOURCE_MAP.json", {
        "date": "2026-10-17", "scope": "Current manuscript and retained supplementary evidence",
        "archive_sources": {k: {"path": str(v[0]), "sha256": v[1]} for k, v in SOURCES.items()},
        "data_file_counts": counts, "copied_files": COPIED,
        "source_bytes_unchanged": True,
        "excluded": ["environment credentials and unrelated working files",
                     "standalone deleted reader-study participant data and plots",
                     "old author questionnaire and mentor-request preparation package"],
        "legacy_plot_note": "Unchanged historical plot code and merged inputs retain the unused reader-study branch; the new entry point calls only historical figures 1-4.",
    })
    print(json.dumps({"prepared": str(DEST), "copied_files": len(COPIED), "data_counts": counts}, indent=2))


def run_check(name, command):
    run = subprocess.run(command, cwd=DEST, capture_output=True, encoding="utf-8", errors="replace", timeout=60)
    dump(DEST / "05_provenance" / (name + ".json"), {
        "command": [str(c) for c in command], "exit_code": run.returncode,
        "stdout": run.stdout, "stderr": run.stderr})
    if run.returncode:
        raise RuntimeError(name + " failed:\n" + run.stderr[-4000:])
    print(name + ": passed", flush=True)


def verify():
    run_check("package_content_check", [sys.executable, "-B", "04_code/verify_package.py", "--before-manifest"])
    run_check("original_v21_replay", [sys.executable, "-B", "-I", "-S", "03_data/original_v21/reproduce.py"])
    run_check("cd_fairness_replay", [sys.executable, "-B", "-I", "-S", "03_data/cd_fairness/reproduce.py"])
    run_check("m3_replay", [sys.executable, "-B", "03_data/m3/study/code/run_m3.py", "verify", "--study", "03_data/m3/study"])


def figures():
    output = ROOT / "docs/mentor_figures_QA_20261017"
    plot_python = Path.home() / "anaconda3/python.exe"
    run_check("figures_replay", [str(plot_python), "-B", "04_code/reproduce_figures.py", "--out", str(output)])
    shutil.copy2(output / "figure_reproduction.json", DEST / "05_provenance/figure_reproduction.json")


def scan():
    patterns = {
        "api_token": re.compile(rb"\bsk-[A-Za-z0-9_-]{24,}"),
        "github_token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}"),
        "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "literal_api_key": re.compile(rb'''(?i)(?:api[_-]?key|api[_-]?token|access[_-]?token)["']?\s*[:=]\s*["'][A-Za-z0-9_-]{24,}["']'''),
        "bearer": re.compile(rb"(?i)bearer\s+[A-Za-z0-9_.-]{32,}"),
    }
    findings, total = [], 0
    text_ext = {".py", ".json", ".jsonl", ".csv", ".md", ".txt", ".log", ".xml", ".html", ".ps1", ".yaml", ".yml"}
    def inspect(name, raw, depth=0):
        nonlocal total
        if Path(name).name in (".env", "id_rsa", "id_ed25519", "credentials.json"):
            findings.append({"file": name, "kind": "credential_filename"})
        if Path(name).suffix.lower() in (".zip", ".docx", ".xlsx") and depth < 5:
            with ZipFile(io.BytesIO(raw)) as zipped:
                assert zipped.testzip() is None
                for item in zipped.infolist():
                    if not item.is_dir():
                        inspect(name + "::" + item.filename, zipped.read(item), depth + 1)
        elif Path(name).suffix.lower() in text_ext:
            total += 1
            for label, pattern in patterns.items():
                if pattern.search(raw):
                    findings.append({"file": name, "kind": label})
    for path in DEST.rglob("*"):
        if path.is_file():
            inspect(path.relative_to(DEST).as_posix(), path.read_bytes())
    dump(DEST / "05_provenance/credential_scan.json", {
        "text_records_scanned": total, "findings": findings,
        "scope": "Credential filename and high-confidence token patterns, including nested archives and Office XML; not a complete privacy audit"})
    if findings:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
        raise RuntimeError("Review credential candidates before packaging")
    print("credential scan: passed (" + str(total) + " text records)")


def finalize():
    assert not ARCHIVE.exists(), "Preserve existing archive"
    for name in ("package_content_check", "original_v21_replay", "cd_fairness_replay", "m3_replay", "figures_replay"):
        result = json.loads((DEST / "05_provenance" / (name + ".json")).read_text(encoding="utf-8"))
        assert result["exit_code"] == 0, name
    scan()
    figureqa = json.loads((DEST / "05_provenance/figure_reproduction.json").read_text(encoding="utf-8"))
    assert figureqa["figures_rebuilt"] == 7
    from pypdf import PdfReader
    pages = {stem: len(PdfReader(DEST / "01_paper" / (stem + ".pdf")).pages)
             for stem in ("Manuscript", "Supplementary_Information")}
    assert pages == {"Manuscript": 20, "Supplementary_Information": 12}
    dump(DEST / "05_provenance/DELIVERY_VERIFICATION.json", {
        "status": "passed", "date": "2026-10-17", "pages": pages,
        "current_figures": 7, "document_bytes_match_prior_visual_QA": True,
        "numerical_replays": ["development/formal", "C/D and fairness", "371 M3 pairs"],
        "new_model_calls": 0, "original_data_and_manuscript_modified": False,
        "limits": "File integrity and replay checks do not authenticate historical reviewer identities or establish scientific validity beyond the manuscript's stated scope."})
    # Nested scientific manifests are data too; exclude only the root manifest.
    inventory = {p.relative_to(DEST).as_posix(): {"sha256": digest(p.read_bytes()), "bytes": p.stat().st_size}
                 for p in sorted(DEST.rglob("*")) if p.is_file() and p != DEST / "MANIFEST.json"}
    dump(DEST / "MANIFEST.json", {"created_utc": datetime.now(timezone.utc).isoformat(),
                                  "files": inventory, "files_covered": len(inventory)})
    validation = subprocess.run([sys.executable, "-B", str(DEST / "04_code/verify_package.py")],
                                capture_output=True, encoding="utf-8", timeout=60)
    if validation.returncode:
        raise RuntimeError(validation.stderr)
    with ZipFile(ARCHIVE, "x", ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in sorted(DEST.rglob("*")):
            if path.is_file():
                zipped.write(path, "Paper_20261017/" + path.relative_to(DEST).as_posix())
    with ZipFile(ARCHIVE) as zipped:
        assert zipped.testzip() is None
        assert len(zipped.namelist()) == len(inventory) + 1
        for relative, expected in inventory.items():
            assert digest(zipped.read("Paper_20261017/" + relative)) == expected["sha256"], relative
    report = {"status": "passed", "archive": str(ARCHIVE), "sha256": digest(ARCHIVE.read_bytes()),
              "bytes": ARCHIVE.stat().st_size, "files": len(inventory) + 1,
              "zip_crc_and_all_file_hashes": "passed", "package_verification": json.loads(validation.stdout)}
    dump(ARCHIVE.with_suffix(".verification.json"), report)
    ARCHIVE.with_suffix(".sha256").write_text(report["sha256"] + "  " + ARCHIVE.name + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify", "figures", "finalize"))
    action = parser.parse_args().action
    {"prepare": prepare, "verify": verify, "figures": figures, "finalize": finalize}[action]()
