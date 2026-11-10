# Offline Release-Control Audit Supplement

Prepared on 15 October 2026. Formal controlled model evaluation is pending.
This package is a portable audit of existing records and prepared materials.
It is not the complete live scientific agent or a final submission archive.

## Run

Extract the ZIP, open this directory, and run with Python 3.10 or newer:

```console
python -B -I reproduce.py
```

No package installation, API key, original project path, or network is needed.
The program rejects socket activity and verifies every packaged file before
loading study code. To save all per-controller rows and grouped counts:

```console
python -B -I reproduce.py --output ../offline_results.json
```

Use a new output filename outside this directory. Files are never overwritten.

## Contents and Expected Checks

- Historical pilot: recount 72 CSV rows, with 13 validated, 53 in_progress,
  and 6 ungated. Twelve validated states occur under reviewer overrides;
  one occurs under conflicting evidence. Ungated is a separate state.
- v2 development: 36 planned units, 11 terminal records, 8 units without
  execution failure and 3 affected by execution failure. Recompute final
  artifact eligibility using the independent Decimal oracle; verify all saved
  scores, input bindings, deterministic A/B decisions and mechanical C receipts.
  Unavailable C checks remain failures even where A/B decisions are usable.
- Recorded traces: 15 received responses and 6 API errors; successful responses
  report deepseek-flash. Recorded usage is 13,766 input and 2,561 output tokens.
  Interrupted requests may have additional unknown usage.
- v2.1 preparation: 24 component inputs and 12 planned generation loops,
  with zero model observations. Six component fixtures are eligible and
  eighteen are ineligible according to the independent oracle.

The six-task formal design plans 144 component decisions and 72 constrained
generation loops. These are planned quantities, not observations in this ZIP.

## Interpretation

Replaying a saved semantic receipt does not independently establish entailment,
recover an unavailable model response, or create a new experimental observation.
A/B deterministic replay and C mechanical replay are checks of recorded policy
execution. Historical pilot statistics are recounted from the supplied summary
CSV, not rederived from all original raw scientific runs.

The evidence environment files are evaluator-only truth for audit. They were
not sent to the model-side worker. Inputs and traces document the actual model
interface. The closed synthetic tasks do not establish correctness or novelty
of open-ended scientific plans.

## Provenance and Limits

`MANIFEST.json` records SHA-256 for every file except itself. The original
study manifests preserve pre-call input, policy, order and source hashes.
Selected modules are exact copies from each frozen source archive.
`legacy_release.py` and `score_saved.py` contain exact source segments extracted
by Python AST, with function names and source locations in provenance metadata.
The extraction avoids importing the network-enabled LangGraph application.
Worker and launcher source are included for inspection, not as a complete
live execution distribution.

Checksums detect changes relative to the included manifest; they are not a
digital signature or external preregistration. Keep the separately supplied
ZIP checksum for transfer verification.

This package excludes credentials, environment files, reader-study participant
records, user memory, original Word files and unrelated project data.
No reuse license is asserted here; author ownership, redistribution terms
and the final public archive identifier still require confirmation.
