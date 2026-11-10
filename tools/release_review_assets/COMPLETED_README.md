# Controlled Release Experiments: Completed v2.1 Records

This archive preserves the separate development and formal batches executed
on 15 October 2026. It contains synthetic inputs, evaluator-only environments,
original API traces, final results, scores, frozen manifests, selected exact
source modules, audit reports and figures. It does not contain credentials,
reader-study participant data, or the original manuscript.

Extract the archive and run from its directory:

```console
python -B -I -S reproduce.py
```

Only Python's standard library is needed. The script blocks socket calls,
checks every file hash, verifies frozen inputs, recomputes all final scores and
generation-round eligibility, reproduces aggregate tables and recounts model
identifiers and token use. The script does not call a model or independently
judge semantic entailment.

`reports/<phase>/decision_replay.json` records the additional execution-time
audit of every deterministic legacy decision and C's mechanical receipt checks.
Those receipts were matched to saved raw responses. This is transcript replay,
not an independent human or model assessment. Source for that audit is supplied
in `analysis_source`; running it in the original project requires its original
project context. The portable command above rechecks independent outcome scores.

Development comprises 24 component inputs and 12 generation loops.
Formal evaluation comprises 48 component inputs shared across A/B/C (144
controller decisions) and 72 generation loops. The loops are constrained
synthetic tasks, not original full scientific-agent workflows.

The evaluator-only environment files are supplied for reproduction; they were
not given to the model-side worker. A finite synthetic benchmark with repeated
templates cannot establish general scientific correctness or universal safety.
Safe narrowing and controller-induced repair are distinct outcomes.

Code files in `code` are selected exact frozen sources, except `score_saved.py`,
which contains exact AST-selected functions with a standalone oracle import.
`SOURCE_PROVENANCE.json` records this extraction. This archive is not a complete
live-agent software distribution. No license or external registration is
asserted; final release terms and publication metadata require author review.

`MANIFEST.json` lists SHA-256 hashes. These detect changes relative to the
manifest, but are not a digital signature. The adjacent ZIP checksum is
provided for transfer verification.
