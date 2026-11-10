"""Supplementary M3 methods and cases for the integrated manuscript."""

SUPPLEMENT_M3 = """## Supplementary Methods for receipt interventions

### Fixed transformations and attribution

The identity control used the original JSON unchanged. The ordering control reversed checked_sources, units and every support/counterevidence list. The whitespace control replaced whitespace runs within source quotations with newlines while preserving addressed_quote, labels and other fields. Each family covered all 48 receipts. Both C and W released 9/48 in each control family and preserved all 144 decisions; identity replay reproduced C's complete original reports.

The primary families altered one specified property of an originally accepted receipt. Fabricated quotation substituted a fixed absent string for the first support quotation. Unknown source and unknown passage substituted fixed absent identifiers. Source omission removed the first checked_sources item. Unit omission removed the first planned row while retaining the factual row. Extra unit appended a planned row with a new identifier, and duplicate unit copied the first factual row with its identifier unchanged. Empty support cleared the first factual row's support list. These eight families each had nine variants. Locator mismatch applied to the five accepted candidates with a locator and substituted the genuine full registry passage, which had no matching Figure 2 locator. It also changed semantic support, so the recorded difference is attributed only to the triggered locator check.

The expected errors were unverifiable_source_quote for quotation/source/passage substitutions; incomplete_source_scan for source omission; incomplete_or_extra_plan_units for unit omission/addition; duplicate unit id within invalid_verification_receipt for duplicated identifiers; unsupported_or_uncertain_premise for empty support; and unverified_locator for locator mismatch. All 77 variants triggered the expected check. Schema compliance and policy acceptance are distinct: duplicate identifiers satisfy the frozen schema but violate C's stricter coverage rule. These were policy rejections, not infrastructure failures.

Positive labels alone set factual and completed_own_work verdicts to supported, preserving kinds and references. Positive labels without counterevidence additionally emptied all counterevidence lists, retaining checked_sources and original support. Genuine registry support applied those changes and replaced factual support with the authentic full registry passage, which supplied no numerical result. Each family covered 48 receipts. Completed work as planned applied only to the six receipts with completed_own_work rows: their kinds/verdicts became planned/not_applicable and references were cleared, while the actual candidate assertion of completed experiments remained unchanged. No explanation text was revised in any family.

[[TABLE:m3_all]]

Supplementary Table 4. Complete offline receipt-intervention inventory and outcomes. C/W total releases use each family's variant count; ineligible releases use the number of independently ineligible unchanged candidates. A dash denotes no ineligible candidates, not a zero false-release rate. The 77 primary variants derive from nine accepted parents, and controls/boundaries reuse the same 48 original receipts. All 371 variants satisfy the frozen schema. Source presence, unit coverage, quotation matching and locator checks are mechanical constraints; they do not establish semantic entailment.

### Eligibility and condition breakdown

In the positive-label-only family, C released 10 eligible and zero ineligible candidates; W released all 12 eligible and 30 ineligible candidates. With counterevidence removed, C released all 12 eligible candidates and all 12 T3/T6 conflict candidates, while withholding T2/T4/T5/T7. With genuine registry support, C released the six T0 positives and all 30 T2/T3/T5/T6/T7 candidates, while withholding T1 because of locator mismatch and T4 because of completed-work checks. W released 12 eligible and 30 ineligible candidates in each of these latter families. The completed-work relabeling family yielded zero C releases and six W releases. Candidate outcomes were calculated after authorization, never supplied to C or W.

### Conflict omission case

Variant p009_C__positive_labels_no_counter came from condition T6. The candidate asserted a single uncontested calculated value of 49 for the synthetic time_cutoff task. record_a reported 49 and record_b reported 52. The changed receipt retained checked_sources = [registry, record_a, record_b], preserved the authentic supporting quotation from record_a, changed the verdict to supported and cleared counterevidence. C released the candidate.

The unchanged explanation read: "record_a reports 49, but record_b reports 52 for the same synthetic time_cutoff task, so the value is contested rather than single and uncontested." Thus the receipt remained internally inconsistent. Its acceptance establishes that listing all source identifiers and preserving one genuine support quotation did not enforce complete treatment of conflicting evidence or agreement between explanation and verdict.

### Genuine but non supporting quotation case

Variant p002_C__genuine_registry_support came from condition T5. The candidate still asserted a value of 49, although the only source was the registry. The intervention forced a supported verdict, removed counterevidence and inserted the genuine registry quotation: "All supplied records are synthetic fixtures, not real experiments. The own-experiment ledger is empty: this study has executed no experiments. No numerical observation record is available in this library." C released the candidate.

The unchanged reason stated that no supplied passage established 49. The supporting quotation was authentic but supplied no numerical result and did not support the assertion. This case isolates a semantic limitation of the implemented checks, without representing a naturally occurring coherent verifier response or showing how often a live model would make that error.

### Integrity and replay scope

The input freeze, source-result bindings, raw API receipts and scored records were checked before and after execution. The local callback provided one stored receipt per assessment. No retries or output selection were used. A limited schema interpreter supported exactly the keywords present in the frozen schema because jsonschema was unavailable in the runtime; it is not a general JSON Schema implementation. Independent replay compared full C reports, W decisions and recomputed summaries. All 371 pairs matched and no unexpected blocked network or subprocess events occurred. The test did not change C or add model calls. The earlier same-receipt diagnostic remains 0/48 changed decisions on unmodified receipts."""

RELATED_TABLE_INTRO = """## Supplementary Table 5

Focused comparison with evidence evaluation and runtime enforcement. The five dimensions describe the inspected methods, not a cross-benchmark ranking. References use the main manuscript numbering. Fixed source versions and inspected sections are supplied in the review bundle. Resource entries describe what was examined; no equal-token comparison with this study is implied. Details not established by the reviewed material are left unasserted. The final row describes the present study and is not counted among the twelve related works.

[[TABLE:related_work]]

The comparison supports a limited contribution claim: an implemented evidence-release interface and a controlled diagnosis of its behavior. Atomic fact checking, attribution, additional verification, fallback decisions and runtime policy enforcement all have precedents. The study does not establish a new general enforcement principle, semantic correctness from quotation matching or an accuracy advantage over ordinary second review. The Answering with Faithfulness comparison uses the full proceedings paper, including Sections 3-6. This is a focused comparison, not a systematic review of all relevant work."""
