# Figure legends

**Figure 1. Evidence-linked planning illustrated with one recorded mathematics run.**
(a) The evidence and review portion of F0 is illustrated using the saved evidence map
and selected review records from math01 F0_clean. The displayed question is
shortened from the recorded research question. Twenty-two source records,
deduplicated by DOI, URL or title, have 28 recorded assignments to seven
research concepts. Curves show these assignments; the numbers give assignments
per concept, not confidence scores or counts of independently verified support.
An open coral node identifies the Hardy-Littlewood prime-tuple concept, which
had no assigned sources in the saved tree. This is a system-recorded gap,
not a conclusion about the mathematical literature. Concept labels are shortened.
The candidate object paraphrases the generated, untested comparison of
Granville-type and Cramer-type models and its proposed observables. I1 and I2
are two examples from the ten recorded issues: inadequate parameter support
and a mismatch between the tree gap and source list. The connector from the
gap to review illustrates the corresponding information rather than proving
that it caused a particular retrieval event. Return arrows depict implemented
revision and additional-retrieval routes. They do not imply that every review
triggers both routes or that the displayed snapshot is a temporal reconstruction.
Map versions, issue histories, scores and budgets persist in the run state.
(b) The seventh and final review retained hypothesis/evidence scores of 70/84,
nine active issues, one resolved issue, an additional-search counter of four
and search_exhausted set to true. This counter excludes initial concept and
frontier retrieval. The exported hypothesis report retained in_progress status.
Stored best scores of 72/74
are distinct from this terminal pair. This illustrates export of a retained
state, not successful scientific validation. The general release checks are
detailed in Figure 2; eligible plans can proceed to verification design. Source assignments,
review scores and operational statuses do not establish scientific correctness.

**Figure 2. Versioned evidence, persistent issue states and nominal release checks.**
(a) A schematic map links a question to concepts and source records. Open
squares denote existing sources, filled teal squares denote new sources, and
the open coral concept denotes a gap. A rebuild to version v+1 requires at
least three relevant new sources comprising at least half the source pool;
routine updates retain version v. The illustrated pool grows from three to six
sources and satisfies both conditions. This topology is illustrative, not an
observed run, and does not imply that rebuilding necessarily fills a gap.
(b) Issue IDs and histories persist. Reviewer-assigned states are accepted;
resolved is not an enforced two-score criterion. A resolved issue reactivates
when its new score is below 80. Automatic archival of an active or resolved
issue requires two consecutive recorded scores of at least 88, no reactivation,
no mention in recent review reasons and no designation as the bottleneck focus.
Archived issues reactivate after negative review evidence or a health-check
score below 88. Health checks occur every three rounds. Solid arrows show
forward transitions and dashed coral curves reactivation. Not every possible
reviewer-assigned transition is shown.
(c) Nominal validation requires no anchor block, the target hypothesis score,
dimension and novelty floors, and an evidence score of at least 60.
Exploratory status retains the shared quality and anchor requirements but
permits evidence below 60 with qualifying gap-confirmation, forced-transition
or search-exhaustion flags. Otherwise, the state remains in_progress. The
original implementation can also accept an overridden pass result; these
nominal checks do not establish enforcement under the judge interventions
shown in Figure 4. Displayed values are defaults: four is an additional-search
routing threshold, not a hard global cap. The unchanged-pool soft-search
counter has a threshold of two. Round limits or same-version
stagnation can stop a run with open issues. Eligible plans proceed to
verification design, not execution of scientific experiments. Scores and state
labels are internal assessments rather than measurements of scientific truth.

**Figure 3. Overall review scores and issue-level histories in one mathematics run.**
(a) The math01 F0_clean run proposed a comparison of Granville-type and
Cramer-type prime-gap models using gap autocorrelation, tuple density and
short-interval variance. The comparison was not experimentally tested. All
seven saved review rounds are shown on the full 0-100 scale. Circles and a solid
line denote hypothesis scores; squares and a dashed line denote evidence
scores. The dotted line is this run's hypothesis target of 90. Stored best
scores (72, 74) differ from terminal scores (70, 84); both pairs are in
hypothesis/evidence order.
(b) Small multiples show the recorded scores and states of all ten issues.
Each row has the same 0-100 vertical range with its own baseline; higher marks
within a row indicate higher scores. Horizontal positions are aligned to panel
a. Open coral circles denote active, the filled teal diamond denotes resolved,
and gray dashes denote not recorded. Numbers at right give terminal issue
scores. Lines connect recorded scores; missing early entries are not treated
as zero, resolved or interpolated observations. I8-I10 first appear in round 6;
I10 becomes resolved in round 7. I10 concerns inconsistent definitions of the
paired unit and comparison count. A high issue score alone does not establish
resolution. Abbreviated issue labels are expanded in the frozen plotting data.
All seven overall states remain in_progress. The terminal record contains nine
active issues, one resolved issue and no archived issues. The additional-search
counter reached four, search_exhausted was true and the concept tree remained
at version 1. The saved state and full hypothesis-generation report support
this trace because the final-delivery report was truncated. The recorded
Hardy-Littlewood prime-tuple gap is a system annotation, not an independent
literature assessment. This single case illustrates recorded behavior rather
than estimating general performance or scientific correctness.

**Figure 4. Complete pilot states and a separate blocking intervention.**
(a) Each symbol represents one saved run: six questions in three domains crossed
with 12 conditions, for 72 runs. A dash denotes the ungated flat-retrieval
baseline, where a release gate is not applicable; an open square denotes
in_progress; and a filled blue circle denotes validated. These are system
states rather than independent judgments of correctness. The complete matrix
retains every clean run and the chemistry question released under conflicting
evidence. The totals are 53 in_progress, 13 validated and six ungated.
Both judge-override conditions produced six validated runs each. These two
rows are shaded. Condition labels are shortened; exact identifiers accompany
the data. A single repeat per cell does not support population-level success
or scientific-accuracy estimates.
(b) Six separate intervention runs are paired with the original judge-override
runs by question identifier. Every saved state changes from validated to
in_progress. Best hypothesis scores remain 96, except chem02 at 98, and
evidence scores remain 100 in every pair. The guard unconditionally changes
every validated state to in_progress and the evidence state to searching; it
does not check a separate authorization flag. It demonstrates blocking under
this intervention, not selective authorization, preservation of legitimate
releases or improved scientific correctness. Classification uses the six
available terminal states. All six processes also recorded a subsequent
score-plot write failure on a long Windows path; the figure does not imply clean process
completion. These six runs are not pooled with the 72-run pilot. No additional
experiments were performed to create the figure.

**Figure 5. Exploratory reader evaluation of constructed document pairs.**
(a) Points show mean within-participant differences, processed minus unprocessed,
for five rating items. Bars are existing unadjusted 95% percentile bootstrap
confidence intervals for the mean paired difference, obtained in the frozen
analysis with 20,000 resamples. Numerical endpoints are rounded for display;
plotting uses their original precision. The dashed line denotes zero. P values
are from two-sided Wilcoxon signed-rank tests with Holm adjustment across the
five rating items, not bootstrap test P values. None of the five items meets
the adjusted 0.05 threshold. An unadjusted interval excluding zero must not
be interpreted as a Holm-adjusted significance result.
(b) Stacked bars show numbers preferring each version, with 20 responses per
item. Solid teal denotes processed and hatched gray denotes unprocessed.
The dotted line at ten participants marks equal preference. P values are
from two-sided binomial tests against equal preference, with Holm adjustment
across the three preference items. Bold type identifies the sole adjusted
P value below 0.05: readability, with 16 of 20 responses preferring processed.
Content-quality and trustworthiness preferences are not significant after
correction.
The same 20 participants contributed across items and are not treated as 100
independent observations. Reading order was fixed: unprocessed first,
processed second. Stimuli were constructed document pairs, not a randomized
comparison of independently sampled live system outputs. The main sample,
including responses flagged in the original quality checks, is retained;
existing sensitivity analyses remain separate. Results concern subjective
presentation and preference, not objective scientific correctness. All
estimates and tests are reused from the frozen analysis without new testing.
