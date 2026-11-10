# Inspected implementation snapshot

This directory contains the local source files inspected on 2026-10-13 and
their local Python-module dependencies. It is an inspection snapshot, not a
claim that every supporting file was separately versioned at pilot execution.
Original source bytes are retained; `audit/included_source_files.json` records
source paths, packaged paths and SHA-256 hashes.

The main `src/langgraph_agent.py` is byte-identical to the main-agent file in
the historical 2026-09-30 archive. That archive separately preserves the
historical fault hooks and repair outputs. The new snapshot should not replace
the old archive when inspecting historical experiment provenance.

The original dependency list is retained as `requirements_original.txt`.
It is not a complete locked environment and may omit optional packages.
No live model or network experiment was run during this audit. API keys,
user folders, environment files and credential stores are excluded.

Important implementation boundaries:

- The graph generates sectioned hypothesis text, not schema-enforced
  hypothesis JSON.
- `--make-plan` is optional post-run processing; no populated plan dictionary
  was found in the 72 pilot states.
- The configured search counter threshold can be exceeded through other
  routes.
- The anchor checker uses patterns. It does not verify quoted source content.
- Citation reports are post-run checks, not direct release-gate inputs.
- A forced positive pass result can bypass nominal score checks.
- The blocking guard downgrades every validated result.
- The original canary metric tests selected-state string occurrence. It can
  count a quoted rejection note as a hit and is not an attack-obedience oracle.

See the Chinese audit report for the manuscript corrections and remaining
author confirmations.
