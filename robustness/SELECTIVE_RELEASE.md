# Selective release study

Status: development. No formal study results exist for this implementation.

The agreed Chinese protocol is `docs/selective_release_protocol_20261014.md`.
The candidate question list is `robustness/configs/selective_release_6.json`.
Its questions must remain unused for tuning until source selection and review
are complete. The old six pilot questions are the development set.

## Implementation

- `src/selective_release.py`: C policy, immutable available-source corpus,
  structured semantic verification and deterministic receipt validation.
- `tools/evaluate_release_case.py`: A/B/C on identical input snapshots.
- `src/release_study_runtime.py`: isolated integration with the existing graph.
- `tools/run_release_workflow.py`: one A/C workflow, with fixed retrieval and
  main-reviewer output manipulation isolated from the evidence verifier.
- `tools/prepare_release_study.py`: offline randomization and review templates.

The semantic verifier checks every nonblank line of the plan against the source
packet, with exact supporting and conflicting quotes. Mechanical checks reject
missing units, unknown sources, invented quotes, unverified locators, unhandled
reported conflicts and detectable unsupported own-experiment claims.
This is model-assisted verification, not a sound general entailment algorithm.
It can still misclassify a claim, miss a conflict or accept an irrelevant quote.
Independent humans must assess those errors. Strings, hashes and recorded
coverage attestations do not establish scientific truth.

No human label is supplied to C. Its prompt contains neither condition IDs nor
reviewer quality scores. The verifier is a separate call using the existing
client; it is not claimed to be an independent model family. A forged
`approved=true` receipt is rejected rather than consumed as authorization.

## Prepare without model calls

From the repository root:

```powershell
C:\Users\22011\anaconda3\python.exe tools\prepare_release_study.py --config robustness\configs\selective_release_6.json --output robustness_runs\selective_release_v1_preparation
```

The output directory must not already exist. The tool creates 144 planned
component rows, 72 planned workflow rows, 48 empty input manifests and a blank
human review form. Counts are planned executions, not observations.

## Material format

Each case manifest points to a UTF-8 plan text and a corpus JSON file, with the
SHA-256 of each exact file. The corpus shape is:

```json
{
  "schema_version": 1,
  "sources": [
    {
      "id": "source-001",
      "title": "Actual source title",
      "origin": "Actual stable source identifier",
      "passages": [
        {
          "id": "passage-001",
          "locator": "Figure 2",
          "text": "Actual verbatim source passage, including relevant limitations."
        }
      ]
    }
  ]
}
```

This schema illustration is not a source packet and must not be used as data.
An empty locator means that the passage has no specific figure/table locator.
Do not add gold eligibility, fault flags or support labels to this corpus.
Removing evidence means removing it from all available source paths, including
the verifier packet. Variant manifests need source and plan provenance.

The T7 component case passes its injected retrieval instruction in a separate,
untrusted notes field to the verifier. With the candidate held fixed, this tests
authorization under injected context, not attack effects on text generation.
Full-workflow T7 attack testing would be a separately declared extension.

## Check and execute a case

```powershell
C:\Users\22011\anaconda3\python.exe tools\evaluate_release_case.py --input PATH_TO_CASE.json --development
C:\Users\22011\anaconda3\python.exe tools\evaluate_release_case.py --input PATH_TO_CASE.json --development --execute --output NEW_RESULT.json
C:\Users\22011\anaconda3\python.exe tools\run_release_workflow.py --input PATH_TO_CASE.json --controller C --repeat 1 --development --execute --output NEW_RUN_DIRECTORY
```

Without `--execute`, no model call is made. `--execute` calls the configured
backend and incurs its normal usage. The DeepSeek time/cost guard follows
`DEEPSEEK_OFF_PEAK_ONLY`; the project owner explicitly disabled that restriction
and selected the official DeepSeek backend on 2026-10-14. Do not run the
generated incomplete templates.

For a full workflow, the base plan is checked as part of material provenance but
is never given to the generator. The generator receives only the question and
frozen retrieval passages. A/C share the same library and budget. Persistent
memory and external lookup are disabled for both arms. Each run must use a fresh
process and a new output directory. Terminal state and exit success are separate.

C authorizes the current hypothesis, not a previous best. Its final delivery
contains the approved text, with the authorization scope stated explicitly.
Historical best text and auxiliary verification-design output remain in the
audit artifacts and are not thereby approved. Internal historical review logs
can show the legacy provisional decision; `release_events.jsonl` records the
subsequent actual authorization decision for each review round.

## Formal execution

Formal mode requires reviewed material provenance and a freeze manifest holding
the final policy, model snapshot/access date, required code file hashes,
material file hashes and case-config hashes. No such manifest is generated by
preparation because development and human checks are not yet complete.
`model_snapshot` is an object with `backend`, `name` and `access_date`; formal
mode checks that the active client matches the frozen backend and model.

The case's `provenance.independent_review_records` records distinct reviewer
IDs and record hashes. This is an audit record, not authenticated proof of
reviewer independence; actual initial annotations must be retained separately.
Human outcome labels remain separate, including after formal runs.

Before formal execution, independently verify newly selected sources, test
the live model schema, complete developer calibration and check all code paths.
Do not report the offline tests below as experiment performance.

## Offline tests

```powershell
C:\Users\22011\anaconda3\python.exe -B -m unittest discover -s tests -p "test_selective_release.py" -v
C:\Users\22011\anaconda3\python.exe -B -m unittest discover -s tests -p "test_release_study.py" -v
C:\Users\22011\anaconda3\python.exe -B -m unittest discover -s tests -p "test_plan_release.py" -v
```

Synthetic fixtures in tests deliberately contain invented source text. They
exercise control logic only and must not enter the paper's empirical matrix.

`tools/smoke_release_verifier.py --execute --output NEW_RESULT.json` runs two
real API calls on synthetic development fixtures. Its results are separate
from the study matrix and explicitly marked as synthetic.
The verifier prompt includes the exact output schema. Malformed receipts and
API failures cannot count as passed live integration checks, including when
they withhold release on a negative fixture.

The 2026-10-14 old-math02 development pilot exposed a PDF line-wrap mismatch on
the legal-locator positive case. Quote matching now accepts whitespace and a
line break immediately after a retained hyphen. Words, numbers, signs, and the
hyphen itself are unchanged. Receipts retain the model quote, the exact matched
source span, offsets, source hash, and match method. Original failed results
remain available; the revised code requires a new snapshot before formal use.
