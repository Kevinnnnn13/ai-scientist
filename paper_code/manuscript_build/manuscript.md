# Review scores and evidence based release authorization in scientific planning agents

Authors: [AUTHOR_NAMES_AND_AFFILIATIONS]

Correspondence: [CORRESPONDING_AUTHOR_AND_EMAIL]

## Abstract

Scientific planning agents must distinguish favorable review scores from permission to release evidence-supported claims. We implemented a controller that combines shared quality thresholds, separate evidence review and mechanically checked quotation receipts. Six synthetic task templates under eight conditions yielded 48 paired component inputs. The original controller released all 36 ineligible candidates; selective authorization withheld all 36 and released 10 of 12 eligible candidates, whereas unconditional withholding released none. In 72 constrained generation runs, selective authorization released correct numerical answers in 16 of 18 clean runs. All initial generated artifacts were already eligible, so these runs do not demonstrate repair. In 96 post hoc supplementary evaluations, selective authorization and ordinary second review each withheld 36/36 ineligible inputs and released 9/12 eligible inputs, with 1.76-fold token use for selective authorization. Removing mechanical checks from unmodified receipts changed 0/48 decisions. A subsequent offline study used 371 paired receipt assessments without new model calls. Mechanical checks rejected all 77 constructed constraint violations from nine previously accepted receipts. However, forcing positive verdicts and removing counterevidence released 12/36 ineligible candidates; substituting genuine but non-supporting quotations released 30/36. These constructed interventions demonstrate enforceable receipt constraints while exposing dependence on semantic judgments. The study supports bounded, inspectable release authorization, without establishing an accuracy advantage over ordinary second review.

## Introduction

Language-model agents can coordinate literature search, hypothesis generation, tool use, experiment execution and manuscript preparation [1-5]. These developments form part of the broader application of artificial intelligence to scientific discovery [6]. Research planning occupies a narrower but consequential position within that process: an agent may propose experiments without executing them, yet its output can still be mistaken for established knowledge. A useful planning system must keep proposed actions, supported premises and unsupported assertions distinguishable.

Retrieval supplies potentially relevant material rather than a guarantee that each assertion is supported [7-11]. Similarly, iterative feedback can improve an answer without making the reviewer a reliable authority on its truth [12-14]. Untrusted retrieved text introduces a further problem when instructions embedded in evidence influence evaluation or acceptance [15,16]. Work on verifiability and model-based evaluation motivates inspecting the basis of a judgment rather than treating an overall score as sufficient evidence [17,18]. Evaluation must also measure legitimate task completion alongside failures, because withholding every output trivially prevents false releases [19].

We examine the distinction between review scores and release authorization in a local research-planning agent. The planning implementation uses scholarly retrieval, including OpenAlex [20], a versioned concept tree, persistent review issues, bounded revision and explicit release states. We refer to it descriptively as the research-planning agent, rather than using the name of the separate AI Scientist systems [1,2]. Our implementation does not execute the scientific experiments it proposes. Its historical planning runs provide implementation context; the new controlled benchmark tests a smaller, explicitly defined release interface.

A historical fault-injection pilot exposed two related limitations. A privileged reviewer override could produce validated states despite evidence problems, and a nominal conflicting-evidence condition also produced an unjustified release. A subsequent unconditional guard prevented release but could not establish whether legitimate outputs would survive. We therefore added eligible positive controls and compared an original score-and-pattern controller A, an always-withhold controller B, and a selective controller C that separately reviews evidence and validates its returned receipts.

The formal comparison shows that C can withhold ineligible candidates while releasing some eligible candidates. It also exposes semantic false rejections and a shared upstream scoring bottleneck. Post hoc language-coverage and locator checks, followed by a contemporaneous ordinary-second-review comparison, narrow the interpretation: a second evidence review matched C's aggregate outcomes, and mechanical checks changed no decisions on the observed unmodified receipts. A further offline receipt-intervention study demonstrates their effect on constructed constraint violations and identifies semantic failures that pass those checks. The contribution is a bounded empirical study of an implemented release interface, paired positive and negative controls, and an explicit account of its trust boundaries.

### Relation to evidence evaluation and runtime enforcement

Fine-grained factual assessment and citation evaluation already distinguish source-supported statements from unsupported ones. FActScore decomposes long-form text into atomic facts [10], and ALCE evaluates generated answers and citation quality [11]. RARR researches attribution and revises unsupported content [21], while Chain-of-Verification uses verification questions before producing a final response [22]. CiteCheck studies citation faithfulness with positive and negative examples [23]. Answering with Faithfulness evaluates unified and composed methods for answer generation and faithfulness prediction, using predicted faithfulness to select a fallback response [24]. Accordingly, neither additional verification, claim decomposition nor conditioning downstream behavior on evidence is new in itself.

Runtime enforcement also has direct precedents. AgentDojo measures legitimate task completion alongside injection outcomes [16]. CaMeL separates control and data flows and enforces capability policies [25]. AgentSpec provides event-triggered predicates and enforcement actions, including task-completion events [26]. Progent enforces tool and argument privileges, distinguishing policy narrowing from expansion [27], while Fides constrains information flows using confidentiality and integrity labels [28]. FORGE uses explicit policies, provenance and a reference monitor for agent actions; it also discusses the dependence of guarantees on semantic classifiers [29]. These systems establish relevant precedents for enforcing constraints outside a language model.

Our comparison addresses the release of constrained scientific-planning outputs under specified evidence and verifier-response faults. It does not claim a new general authorization principle or equivalent guarantees to these policy systems. Supplementary Table 5 compares twelve works across the verification object, decision basis, trust boundary, resources and empirical coverage. The comparison is descriptive and source-scoped; it does not rank systems using incomparable benchmarks or treat unverified details as absent.

## Results

### Evaluation scope and controller comparison

The formal benchmark crossed six synthetic task templates with eight conditions, producing 48 component inputs. Each input was evaluated by A, B and C, yielding 144 controller decisions. A separate experiment comprised 72 constrained generation runs: six tasks, two conditions, two controllers and three repetitions. These are 120 execution units, not 216 independent research problems. Development and formal observations were retained separately. All formal units completed without terminal execution or output-protocol failures.

The tasks were mass balance, dilution, time cutoff, fixed-weight portfolio return, linear residual and sample mean. Each task had a fixed numerical environment and a small supplied evidence library. An independent program recomputed numerical answers and evaluated evidence availability, conflicts, references and claims of completed experiments. It did not use the controller's verdict as ground truth. C received the public evidence and candidate, not the private environment or outcome labels.

A applied the existing score thresholds and conservative pattern screen. B retained A's calculation and downgraded every validated result. C used the shared quality thresholds, a separate same-model evidence review and mechanical checks of unit coverage, source coverage, quotation spans, locators and execution-state assertions. Thus, C's review role was separate from the quality reviewer, but not an independent model family. Table 1 summarizes formal outcomes, and Figure 1a gives the condition-level release matrix.

[[TABLE:formal]]

[[FIGURE:fig1]]

### Selective release with residual false rejection

Of 36 ineligible component candidates, A released 36, whereas B and C released none. Of 12 eligible candidates, A released six, B none and C ten. C therefore demonstrated selective release within this benchmark, rather than the blanket withholding represented by B. Its observed zero false releases concern these 36 designed inputs and do not establish zero risk in an unrestricted population.

The positive controls distinguish two different behaviors. For ordinary correct candidates without a figure locator, A released 6/6 and C 4/6. For correct candidates carrying a supported textual Figure 2 locator, A released 0/6 and C 6/6. C improved handling of these legitimate locators but did not dominate A on every condition. The two C false rejections occurred in dilution and linear-residual cases.

Ineligible conditions comprised missing evidence, conflicting evidence, fabricated own completed experiments, missing evidence with reviewer override, conflicting evidence with reviewer override, and missing evidence with instructions in untrusted retrieval notes. Each contained six candidates. A released all six in each condition; B and C released none. Only the two reviewer-override conditions directly exercised privileged pass/score intervention. The total 36/36 must therefore not be described as 36 privileged-override failures.

Component scores were controlled inputs set high enough to pass the shared quality thresholds, with full scores under the override conditions. These observations test whether authorization detects a mismatch between a favorable review and the supplied evidence. They do not estimate the prevalence of naturally occurring reviewer mistakes or ordinary scientific errors.

### Generation runs separate numerical completion from safe narrowing

In clean constrained generation, C released correct numerical answers in 16/18 runs, while A released none of 18. All 18 final A answers were nevertheless eligible under the independent outcome rules. Each retained a legitimate Figure 2 reference that activated A's pattern screen. Consequently, A's zero released numerical answers is not zero arithmetic accuracy. Its three-round limit expired without release. C's 16 successful runs released after one round; its two withheld runs reached three rounds (Figure 2).

[[FIGURE:fig2]]

Under missing evidence with reviewer override, A and C each released accurate statements of insufficiency in 18/18 runs. These statements correctly described the available library and did not invent a numerical observation. We count this behavior as released safe narrowing, not successful completion of the requested numerical task. It is a useful outcome under the specified evidence constraint, but the absence of a between-controller difference prevents attributing it specifically to C.

All 72 first-round artifacts were already eligible. No run demonstrated conversion of an ineligible initial artifact into an eligible one. The experiment therefore does not establish controller-induced repair. No ineligible final artifacts were observed either, leaving the denominator for a workflow false-release rate at zero. This quantity is undefined here, rather than an empirical 0% false-release rate. Component and generation experiments answer complementary questions and are not pooled.

### Two distinct sources of false rejection

The formal component false rejections were u0025, a linear-residual answer of 24.0, and u0048, a dilution answer of 6.8. The verifier recognized that the numerical values appeared in their sources. It nevertheless treated a registry statement that the records were synthetic fixtures rather than real experiments as counterevidence to the candidate's statement of a single uncontested synthetic result. The cited spans were mechanically verifiable, but their interpretation was wrong (Figure 3).

The clean generation false rejections, u0098 and u0104, had a different cause. Both gave the correct linear residual of 24 with valid references in all three rounds. The quality reviewer assigned a total score of 88 each time, below the frozen threshold of 90, despite largely approving the answer or requesting explanation outside the constrained output contract. Evidence verification was not invoked in any of these six rounds. These are failures of the shared upstream quality gate, not failures of C's quotation checking.

[[FIGURE:fig3]]

These cases show why recording intermediate decisions matters. A withheld output can arise from a low upstream score or a mistaken evidence interpretation, and the remedies would differ. Inspectable receipts make the latter error diagnosable, but do not transform an incorrect semantic judgment into a correct one.

### Post hoc baseline fairness and locator sensitivity

Inspection revealed that A's own-completed-experiment patterns primarily covered Chinese, whereas T4 used an English assertion and C included an English pattern. We evaluated a separately named A-English variant that added the corresponding English coverage while retaining A's thresholds and privileged-pass semantics. All six T4 false releases disappeared. Total false releases fell from 36/36 to 30/36; eligible releases remained 6/12. T4 therefore cannot be used as clean evidence that the architectural difference alone explains the original advantage.

We also removed only the legal locator from saved candidates, rerendered them and replayed A with the original scores. All six component T1 candidates then passed. Among the 18 saved A clean-generation final candidates, 15 passed; the remaining three were linear-residual cases with final scores of 88. All edited candidates remained eligible. The generation advantage was therefore largely sensitive to the locator rule, with an additional scoring bottleneck. This fixed-score counterfactual is not a new generation experiment: it does not measure how reviewers would react to edited text or how a revised agent would behave over multiple rounds.

These analyses were specified after inspecting the formal results, conducted without new model calls and saved separately. They do not overwrite the original A results or constitute a new untouched test set.

### Ordinary second review matches aggregate selective-release outcomes

We next compared unchanged C with an ordinary second-review controller D on the same 48 component inputs. Both arms used the same supplied candidate, sources, untrusted notes, model configuration and maximum number of review attempts. D produced an overall evidence verdict without C's mechanically checked quotation receipts. The supplementary rules and order were frozen before these new calls, although the inputs and original results had already been inspected.

All 96 evaluations completed without execution or protocol failure. Both C and D withheld 36/36 ineligible candidates and released 9/12 eligible candidates (Table 2; Figure 1b). C released 4/6 ordinary positives and 5/6 locator positives; D released 5/6 and 4/6, respectively. The paired decisions comprised seven releases by both arms, 37 withholds by both, two C-only releases and two D-only releases. Equal aggregate counts therefore do not mean identical case-level behavior.

[[TABLE:supplement]]

C's supplementary 9/12 is a separate observation from the original formal 10/12. We retain both rather than selecting the more favorable run. Supplementary errors again included mistaken treatment of synthetic provenance as counterevidence. D also rejected a linear-residual answer by incorrectly treating 24 and 24.0 as different numerical results. The separate calls remained fallible even with temperature set to zero.

A further diagnostic reused all 48 C receipts. Replacing full mechanical receipt checking with a semantic-label-only rule changed 0/48 decisions. We denote this weaker deterministic rule W below; it is not D and makes no new model call. The result shows that mechanical checks did not affect release decisions on these observed unmodified receipts. Together with the ordinary-second-review comparison, it prevents attributing the measured improvement over A specifically to the receipt machinery. The following intervention study tests a different question: whether specified modifications to the same saved receipts change that conclusion under a faulty-verifier-response boundary.

### Offline receipt interventions expose mechanical effects and semantic limits

The offline study used all 48 saved C receipts and evaluated 371 constructed variants with both C and W, yielding 742 rule decisions and no new model calls. Both rules preserved their original decisions for all 144 identity, ordering and quotation-whitespace controls. Identity replay reproduced C's complete saved reports. The original 0/48 decision difference on unmodified receipts therefore remains unchanged.

The primary analysis selected only the nine previously accepted receipts. Eight constraint-violation families contributed nine variants each, and locator mismatch applied to five receipts, for 77 variants in total. C withheld all 77, whereas W released all 77. Each triggered its specified mechanical error. The interventions altered quotations, source or passage identifiers, source-list coverage, unit coverage, support presence or locator matching (Supplementary Table 4). All variants satisfied the saved JSON schema. The unchanged candidates remained eligible, so withholding a corrupted receipt is not a false rejection of the original intact input. These 77 variants share nine parents and do not represent independent tasks.

Boundary diagnostics exposed failures when the verifier's semantic fields were altered (Table 3). Forcing positive verdicts alone caused no ineligible releases by C (0/36). Additionally removing counterevidence caused 12/36 ineligible candidates to be released, covering all T3 and T6 conflict cases. Replacing factual support with genuine registry quotations that established no numerical result caused 30/36 ineligible releases. C withheld all six variants that relabeled completed-work assertions as plans; W released all six. These latter interventions retained the candidate's assertion of completed experiments.

[[TABLE:m3_boundary]]

In one conflict case, both record_a and record_b remained in checked_sources, but only the supporting record survived in the reference lists. In a missing-evidence case, the purported support explicitly stated that no numerical observation was available. Both altered receipts were accepted by C. Their original explanations were deliberately retained and contradicted the forced supported verdicts; the controller checks that an explanation is nonempty, not that it is semantically consistent with the verdict. These are schema-valid corrupted receipts, not naturally occurring coherent model responses. All 371 paired outputs replayed exactly, with zero execution faults. The results demonstrate specified mechanical enforcement, not natural error rates, adaptive-attack resistance or an accuracy advantage over D.

### Historical planning runs provide context rather than pooled validation

The original frozen planning pilot contained 72 runs over six research questions and 12 conditions. Its saved states were 53 in_progress, 13 validated and six ungated. Twelve validated states occurred in the two privileged reviewer interventions; one chemistry case was released under conflicting evidence without that override. Logging made these failures discoverable, but release control failed in the affected runs. The historical unconditional intervention withheld all six paired validated states, although all six processes subsequently failed during plotting after saving their terminal states.

Supplementary Figures 1-4 preserve the historical architecture, mathematics trajectory and complete state matrix. These observations concern a larger planning workflow with different outputs and outcome rules. They are neither additional samples in the synthetic benchmark nor proof of its generalization to scientific planning. A reconciled claim-audit record is described separately with its assessor-provenance limitation; reader-presentation outcomes are not used as release-control evidence.

## Discussion

### What the separation of review and authorization establishes

The tested high-score release rule was insufficient to reject supplied candidates with missing or conflicting evidence. Both an evidence-review controller and the more structured selective controller rejected those candidates while allowing some supported ones. The always-withhold reference confirms that selective permission is a different outcome from zero false releases achieved by rejecting everything.

This supports a practical distinction between a candidate's review score and the evidence needed for its release. It does not establish that C has greater release accuracy than ordinary second review: the contemporaneous comparison produced the same aggregate counts, and the unmodified-receipt diagnostic changed no decisions. The offline interventions add narrower evidence that deterministic receipt constraints can change authorization when those constraints are violated. They also show that a structurally acceptable receipt can still authorize an unsupported claim. Explicit runtime enforcement and evidence-conditioned decisions have relevant precedents [24-29]; our contribution is the implementation and controlled diagnosis of this release interface, rather than a new general safety principle.

In the contemporaneous comparison, C used 67,118 tokens versus 38,125 for D despite equal aggregate release counts. The observed 1.76-fold token use does not establish a benefit in release accuracy for that additional consumption, nor does the small comparison establish general equivalence. W is a weaker rule applied to C's saved receipts, so its behavior under receipt intervention cannot substitute for a comparison with D under a matched threat model.

### Traceable evidence remains semantically fallible

The original component failures are useful counterexamples to equating quotation matching with factual verification. A quoted sentence can be authentic while its use as evidence is mistaken. C confused a provenance qualification with a substantive contradiction; D made related mistakes and a numerical-equivalence error. A shared model family supplies no independence guarantee merely because it is assigned another role.

The upstream score failures expose a second limitation. A strict authorization layer cannot release an eligible answer if a prior quality gate blocks it. The constrained output and review rubric were explicitly aligned before formal execution, yet the reviewer still requested content outside that contract or applied a lower score without a corresponding substantive defect. We report these errors without tuning thresholds on the observed formal outcomes.

The receipt interventions expose a related failure boundary. Authentic quotations do not establish that their meaning supports a claim, and a complete checked_sources list does not establish that relevant opposition was reported. In the positive-label interventions, retaining contradictory explanation text did not prevent release once other blocking fields were removed or replaced. Detecting these semantic inconsistencies or omitted opposition would require capabilities beyond the currently implemented mechanical checks. This limitation concerns faulty verifier responses and should not be conflated with the earlier score-override intervention.

### Interpreting safe narrowing and comparative gains

The missing-evidence runs show that an accurate statement of insufficiency can be eligible for release while leaving the requested calculation incomplete. This distinction avoids rewarding either invented completion or indiscriminate refusal. However, the generator produced these eligible statements before the release controller acted, and A performed identically to C. The result concerns the generation-and-release system under the fixed prompt and evidence library, not demonstrated repair or C-specific attack resistance.

The sensitivity analyses also change the interpretation of the normal-generation comparison. Most A rejections were directly attributable to a legitimate locator activating a blanket screen. Removing that locator at fixed scores recovered 15 releases. C's original 16/18 versus A's 0/18 is an observed difference, but not a general estimate of how much selective authorization improves a normally operating scientific agent.

### Limitations and scope

The benchmark has six simple templates, a small fixed evidence library and a restricted answer schema. The material generator uses the same task rules as the independently implemented outcome scorer; computational independence does not eliminate shared specification error. The formal numerical instances differ from development values, but the task families were preconstructed. Repetitions and condition variants are not independent research questions.

The experiments use one provider and one returned model identifier. The requested API alias does not pin a server-side weight snapshot. The C/D supplement was designed after seeing the original results and reused known inputs. It matches the opportunity for an additional review call, not identical prompt lengths, actual token consumption or every internal instruction. Consequently, it compares two implementations rather than isolating a single architectural component.

The experiments cover prescribed evidence faults, a privileged review-field intervention, one fixed instruction in untrusted notes and a separate offline verifier-response intervention. They do not cover adaptive adversaries, malicious controller-code changes, compromised signing or storage systems, long-document retrieval, image interpretation, or unrestricted model-generated plans. The receipt interventions were designed after inspecting the code and saved data. Freezing them before evaluation does not make them preregistered or held out, and their correlated variants cannot estimate natural verifier error rates. Source hashes and transcript replay establish consistency of saved execution, not external scientific truth. There were no independent human expert assessments of the synthetic outputs.

The historical pilot does not resolve these limitations. Its open planning outputs have different criteria, and its six clean runs were all withheld without independent positive-release labels. The historical claim sheets were reconciled and their human versus model roles were not authenticated. Those records are descriptive context, not independent inter-rater validation.

Overall, the study provides bounded evidence that reviewing supplied evidence can prevent failures of a tested score-driven release rule while retaining some legitimate releases. The offline interventions show that explicit receipt constraints can affect authorization, while identifying semantic failures that those constraints permit. The data support separating review scores, evidence judgments and release records, with clearly stated trust assumptions. They do not establish an accuracy advantage over ordinary second review, comprehensive semantic verification or demonstrated repair of erroneous outputs.

## Methods

### Planning implementation and historical provenance

The research-planning agent is implemented in Python with a LangGraph state machine. It coordinates reasoning and tool use [30], literature retrieval, concept-tree construction, gap analysis, hypothesis generation, quality review and verification design. The main planning hypothesis is prompted to follow sections but is not schema enforced. An optional post-run command generates a 12-field plan; the historical pilot did not exercise that command, the API input guard or uploaded-document parsing. The controlled benchmark does not claim to validate those paths.

Historical run records contain candidate text, source assignments, review dimensions, issue histories, search counters and release reasons. Routine rounds reuse a concept tree; a rebuild requires at least three relevant new sources comprising at least half the source pool. Review defaults to ten rounds with same-version stagnation patience of three. The additional-search threshold of four is a routing threshold rather than a global cap; 18 of 66 historical full-pipeline runs exceeded it, reaching ten. These implementation details and the original figures are retained in the Supplementary Information.

### Controlled materials and independent outcome rules

The v2.1 material generator created development and formal numerical instances of six operations. A source registry declared which records were available and stated that no own experiments had been executed. A normal record supplied task inputs, the calculation rule and its reported result. It also carried a textual Figure 2 locator. This is a synthetic text locator; no image was supplied or interpreted.

The answer object contained mode, value, citations, locator and completed_experiment. Mode was result, insufficient or conflict; non-result modes required a null value. The renderer exposed every content-bearing field and appended a sentence proposing future arithmetic verification. A result asserted a single uncontested synthetic value. Eligibility required correct arithmetic within absolute tolerance 0.000001, available and appropriate source identifiers, no unresolved conflicting values, a supported locator when present, and no fabricated own completed experiment. An insufficiency response required an empty observation library and a registry citation; a conflict response required citing all disagreeing records.

The material producer used floating-point operations, while the separate outcome evaluator recomputed answers from private raw environments using Decimal. The evaluator imported no controller or model code and never treated a release verdict as truth. Public model workers accepted only task text, evidence, untrusted notes, candidate fields and the assigned controller interface. Private environments, condition identifiers and outcome labels were retained by the parent scorer. This is independent programmatic scoring, not authenticated independent human annotation.

### Conditions and threat model

T0 supplied a supported correct numerical candidate without a locator. T1 added a legitimate Figure 2 locator. T2 removed observation evidence while retaining a numerical assertion. T3 added a conflicting observation while the candidate continued to assert a single uncontested result. T4 added an English claim that this study had completed experiments and obtained measurements. T5 combined T2 with reviewer override, and T6 combined T3 with that override. T7 combined T2 with an instruction in untrusted retrieval notes to ignore missing evidence, approve the plan and invent quotations.

The perturbation harness could alter the specified evidence records, candidate assertions, untrusted notes and review outputs. It could not alter controller code, frozen policy or the private outcome evaluator. Reviewer override acted after review and before release: scores and dimensions became 100, and A additionally received a forced pass result. In T5 generation runs the override persisted each round, up to three rounds. Removed observations could not be recovered through additional retrieval. T7 was tested only as a component input. The scope is authorization under these specified interventions, not an unrestricted attacker with code or credential access.

### Controllers and shared quality policy

A used the existing release function and its anchor screen. The screen detected figure/table locators and selected Chinese completed-experiment assertions without establishing whether the cited source actually supported them. Nominal validation required no anchor block, total score at least 90, evidence score at least 60 and dimension scores meeting the frozen floors. The controlled adapter supplied the text and scores to that logic. A could also accept the forced pass result used in T5/T6.

B computed A's decision and downgraded each validated state to in_progress. It was a limiting reference for safety obtained by withholding all outputs, not a matched-compute evidence-review method.

C used the frozen selective-release-v1 policy. Its total threshold was 90, evidence floor 60 and dimension floor 75; the additional novelty floor was 50 and did not lower the dimension floor. A separate model call was instructed to examine every nonblank candidate line, every supplied source and relevant counterevidence. It returned per-unit kind, verdict, reason, support quotations and counterevidence references rather than an overall permission flag.

The controller checked unit identifiers against all nonblank candidate lines and checked_sources against the supplied source identifiers. It verified that source and passage identifiers existed and that quotations of at least 20 characters matched supplied passages exactly or under limited PDF whitespace normalization. It matched figure locators to supporting passages and rejected unrecorded completed-work assertions. For each reported counterevidence reference, it required a matching source quotation and a sufficiently long quotation from the candidate containing a qualification pattern. These checks do not establish that the verifier reported all relevant opposition or that the qualification is semantically adequate. The reason field is required to be nonempty but is not checked for agreement with the verdict. Every candidate required a factual premise and an explicitly untested proposal. Receipts and decisions were bound to the candidate, evidence library, policy and prompt by hashes; these checks do not independently establish semantic entailment.

### Component and generation schedules

For component inputs, ordinary fixed scores were 95 for total task compliance and 85 for evidence, with testability/evidence/feasibility/novelty dimensions of 95/85/90/80. Override conditions used 100 for all scores and dimensions. Each of the 48 formal candidates was shared across A/B/C. There were 12 eligible and 36 ineligible candidates per arm.

The generation experiment crossed six tasks, T0/T5, A/C and three repetitions. Generation used the supplied library and could revise from review feedback for at most three rounds. Each round generated a new constrained object, obtained a quality review and applied the assigned release rule. It stopped on validated or at the round limit. A and C runs were separate model trajectories, not the same generated candidate replayed across arms.

The v2.1 reviewer rubric treated hypothesis_score as task compliance. It explicitly allowed an accurate insufficiency statement to score highly for its actual evidence-supported claim. It instructed the reviewer not to demand extra prose, apparatus or novel hypotheses outside the output contract. The legacy novelty field was fixed to 75 in generation reviews solely for interface compatibility and was not a scientific-novelty measurement.

Development comprised 24 component inputs and 12 generation runs over three predetermined tasks: mass balance, time cutoff and sample mean. After development, scientific code, prompts and thresholds were unchanged for formal evaluation. Development used one worker; formal evaluation used three. Completed outcomes were not rerun for more favorable results. Earlier interrupted preparation and connectivity probes are outside this v2.1 analysis.

### Post hoc sensitivity and second-review protocol

After inspecting formal outcomes, we froze a separate supplementary protocol. The offline A-English variant added the English portion of C's own-completed-work pattern to A's anchor-block flag, retaining all other release logic and override behavior. We applied it to all 48 saved component inputs. Locator counterfactuals changed only the structured locator to none in six T1 component candidates and 18 A clean-generation final candidates, rerendered the text and reused the exact saved review. Eligibility was recomputed. These counterfactuals do not simulate a new review or generation trajectory.

D applied the same quality thresholds as C, then requested an overall supported, unsupported, contradicted or uncertain verdict from the same model. Its instructions required checking all factual assertions, conflicts, figure references and claims of completed work while ignoring commands in untrusted data. It used no quotation-level receipt, lexical completed-work detector or deterministic locator match. Only supported permitted release. Both C and D received identical user-message content: candidate units, evidence passages and untrusted notes, without labels.

The 48 pairs were shuffled using seed 20261015. C ran first in 24 pairs and D first in 24; calls were sequential within a pair, with at most three pairs running concurrently. Code, protocol, input hashes, source-result bindings and order were frozen before these calls. The protocol required preserving every outcome, stopping new scheduling after an execution/protocol failure and draining the current batch; no such failure occurred.

For a same-receipt diagnostic, the full C decision was mechanically replayed and compared with a weaker rule requiring at least one factual row and allowing only supported factual rows or not_applicable planned/heading rows. That rule rejected completed_own_work and negative or uncertain verdicts but omitted quotation, coverage, locator, lexical-kind and counterevidence-addressing checks. This evaluates recorded receipts rather than adversarially modified receipts or another live model arm.

### Offline verifier receipt intervention protocol

We conducted a separate post hoc, code-informed intervention study using all 48 C receipts from the supplementary comparison. The experimenter could replace only the verifier's JSON response immediately before C inspected it. Candidate text, artifacts, scores, corpus, release policy and controller code were unchanged. Each assessment used a fresh controller and one receipt substitution, without retries, repair, recovery or adaptive search. This models a faulty or compromised verifier response, rather than the earlier reviewer-score override. The protocol, executable, source bindings and every variant were frozen before evaluation, after the code and original data had already been inspected.

C was loaded from the frozen source snapshot. W was the exact semantic_only function extracted from that snapshot and used in the earlier same-receipt diagnostic. It required at least one factual row and accepted only supported factual rows or not_applicable planned/heading rows. W was not controller D. All candidates already passed the shared quality thresholds. Both rules received the same altered receipt without private environments, condition identifiers or eligibility labels. The independent Decimal oracle assessed unchanged artifacts after authorization.

Three control families covered all 48 receipts. Nine primary mechanical families were applied only to the nine originally accepted receipts, with locator mismatch applicable to five, yielding 77 variants. Three semantic-field boundary families covered all 48 receipts, and completed-work relabeling covered six, yielding 150 boundary variants. Exact transformations and denominators are in Supplementary Table 4. Original explanations were preserved. Every variant was checked against the frozen schema using an implementation restricted to its actual keywords. A local stub supplied each receipt once; a Python audit hook blocked connections, DNS, binding and child-process execution. Its deliberately blocked self-test was recorded separately from unexpected attempts. Full reports and summary statistics were independently replayed. The study made no new model calls.

### Model calls and resource reporting

All new live evaluations used the existing DeepSeek client. Requests used the deepseek-chat alias; all successful development, formal and supplementary responses reported deepseek-flash. Structured requests used temperature 0, JSON mode and an output-token ceiling of 8192, with a 120-second request timeout, zero SDK retries and at most one application-level retry. The alias does not identify a pinned weight snapshot.

Development recorded 66 successful responses and 74,780 tokens. Formal evaluation recorded 306 successful responses, 281,254 input tokens and 38,477 output tokens, totaling 319,731. The C/D supplement recorded 96 successful responses, 89,178 input tokens and 16,065 output tokens, totaling 105,243. No API errors were recorded in these completed phases. Totals across the three phases were 468 responses and 499,754 tokens, excluding the connectivity probe. Each supplementary arm completed 48 successful calls. C used 55,701 input and 11,417 output tokens (67,118 total), whereas D used 33,477 input and 4,648 output tokens (38,125 total). C therefore used 1.76 times as many total tokens as D. Per-run counts were reconciled against the saved API response usage. These provider-reported totals count cached prompt tokens within input tokens; they are not billing or latency estimates. The comparison matches review-call opportunities rather than actual token consumption.

Offline fairness checks, the unmodified-receipt diagnostic and the subsequent receipt interventions made no new model calls; they do not add to these API or token totals.

### Statistical Analyses

Results are descriptive paired counts with explicit denominators. False release is validated among independently ineligible candidates; false rejection is withholding among eligible candidates. Eligible release, numerical task completion and safe narrowing are separate outcomes. Execution or protocol failures are separately counted and are not successful rejections. A false-release proportion is not estimated when there are no ineligible final artifacts.

We do not treat condition variants or repeated calls as independent scientific tasks, pool historical and synthetic populations, or present significance tests based on inflated decision counts. C/D disagreements are reported as paired counts. Original formal, development and post hoc supplementary observations remain separately identified. No outcomes were excluded to improve the reported efficacy.

For receipt interventions, the primary endpoint was C withholding with W releasing an originally accepted, mechanically corrupted receipt. Candidate eligibility and receipt validity were kept separate. We report each boundary family's total releases and releases among independently ineligible candidates using its own denominator. The 371 assessments derive from 48 receipts and six templates; primary variants share nine accepted parents. They are not independent samples or additional live evaluations and are not pooled with original false-release proportions.

### Audit and reproducibility

All 120 formal units were independently rescored, and 112 intermediate generation artifacts were recomputed. Mechanical replay reproduced 168 A/B decisions and 88 C decisions, with 82 actual C receipts bound to raw responses and six quality-blocked decisions without a verifier call. The supplementary analysis reproduced all 96 decisions and bound their returned receipts to raw responses. Frozen original and supplementary source/input hashes were checked.

The original completed-results archive contains 757 verified files and passes isolated standard-library replay and a tamper-rejection check. A separate revision package adds the fairness records, C/D inputs and responses, supplementary protocol, per-case scores, figure inputs and reproducibility scripts. Replay validates consistency of saved artifacts and rules; it is not a new model run or independent semantic validation.

The offline receipt study bound all 48 original receipts to saved API responses and retained complete altered receipts, changed-field paths, source bindings and 371 paired outputs. Frozen source, variant and result hashes were checked; independent replay reproduced every full C report, W decision and summary. An isolated extracted copy also passed all 371 pairs. No execution faults, unexpected network attempts or new model calls occurred. The deliberate network self-test was blocked before connecting. The included manifests check file consistency and do not constitute external timestamping or preregistration.

## Data availability

The original development and formal synthetic records are supplied in controlled_release_v21_completed_20261015.zip, SHA256 56f10121d14750518de9fa7fa70cdd9b9456a2ac8744ed289e6a1ec44823606f. The accompanying revision review package contains the additional fairness analysis, 96 C/D evaluation records, private synthetic environments used for independent scoring, frozen protocol, figures and a minimum-dataset description. These synthetic datasets contain no participant responses or API credentials. Historical planning evidence and its limitations are described separately in the Supplementary Information. [PUBLIC_ARCHIVE_IDENTIFIER_AND_DATA_LICENSE_TO_BE_CONFIRMED_BY_AUTHORS]

The additional offline verifier-receipt dataset includes the frozen protocol, original receipt bindings, 371 variants, paired decisions, eligibility-stratified summaries and executable replay code. It is supplied separately from the original formal and C/D datasets. Each variant's parent and exact changed fields are retained, and both successful checks and boundary failures are included. The integrated review bundle preserves the earlier experiment archives and adds the revised manuscript, Supplementary Information and a version-specific primary-source comparison.

## Code availability

The accompanying review package supplies the code needed to reconstruct the controlled results from saved inputs and responses, including the independent outcome evaluator and release checks. It also supplies supplementary execution and figure-generation sources. Live execution requires the documented Python dependencies and access to the same model service; identical future responses are not guaranteed. The package is not a distribution of every optional feature in the planning agent. [PUBLIC_CODE_ARCHIVE_IDENTIFIER_LICENSE_AND_ACCESS_TERMS_TO_BE_CONFIRMED_BY_AUTHORS]

## Generative artificial intelligence

Generative artificial intelligence assisted experiment orchestration, code development, analysis drafting and manuscript preparation. Historical claim-audit records identify model assistance and have incompletely authenticated assessor roles. The synthetic outcomes were evaluated programmatically rather than labeled by authenticated independent human experts. Authors must verify the evidence, interpretation and final manuscript before submission; no artificial intelligence system is an author.

## Funding

[FUNDING_STATEMENT_TO_BE_CONFIRMED_BY_AUTHORS]

## Author contributions

[AUTHOR_CONTRIBUTIONS_CONFIRMED_BY_ALL_AUTHORS]

## Competing interests

[COMPETING_INTERESTS_STATEMENT_TO_BE_CONFIRMED_BY_ALL_AUTHORS]

## Ethics and participant information

The controlled release experiments use synthetic records and model outputs. Participant preference data from the earlier reader comparison are not analyzed or reported in this manuscript. [AUTHOR_CONFIRMATION_OF_ETHICS_APPLICABILITY_AND_PROVENANCE_OF_RETAINED_HISTORICAL_RECORDS]

## References

1. Lu, C., Lu, C., Lange, R. T., Foerster, J., Clune, J. & Ha, D. The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery. arXiv:2408.06292 (2024).

2. Yamada, Y. et al. The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via Agentic Tree Search. arXiv:2504.08066 (2025).

3. Boiko, D. A., MacKnight, R., Kline, B. & Gomes, G. Autonomous chemical research with large language models. Nature 624, 570-578 (2023).

4. Bran, A. M. et al. Augmenting large language models with chemistry tools. Nature Machine Intelligence 6, 525-535 (2024).

5. Si, C., Yang, D. & Hashimoto, T. Can LLMs Generate Novel Research Ideas? A Large-Scale Human Study with 100+ NLP Researchers. International Conference on Learning Representations (2025).

6. Wang, H. et al. Scientific discovery in the age of artificial intelligence. Nature 620, 47-60 (2023).

7. Lewis, P. et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. Advances in Neural Information Processing Systems 33, 9459-9474 (2020).

8. Gao, Y. et al. Retrieval-Augmented Generation for Large Language Models: A Survey. arXiv:2312.10997 (2023).

9. Ji, Z. et al. Survey of Hallucination in Natural Language Generation. ACM Computing Surveys 55, Article 248 (2023).

10. Min, S. et al. FActScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation. Proceedings of EMNLP, 12076-12100 (2023). doi:10.18653/v1/2023.emnlp-main.741.

11. Gao, T., Yen, H., Yu, J. & Chen, D. Enabling Large Language Models to Generate Text with Citations. Proceedings of EMNLP, 6465-6488 (2023). doi:10.18653/v1/2023.emnlp-main.398.

12. Shinn, N. et al. Reflexion: Language Agents with Verbal Reinforcement Learning. Advances in Neural Information Processing Systems 36 (2023). doi:10.52202/075280-0377.

13. Madaan, A. et al. Self-Refine: Iterative Refinement with Self-Feedback. Advances in Neural Information Processing Systems 36, 46534-46594 (2023).

14. Huang, J. et al. Large Language Models Cannot Self-Correct Reasoning Yet. International Conference on Learning Representations (2024).

15. Greshake, K. et al. Not what you've signed up for: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection. arXiv:2302.12173 (2023).

16. Debenedetti, E. et al. AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents. Advances in Neural Information Processing Systems 37 (2024). doi:10.52202/079017-2636.

17. Liu, N. F., Zhang, T. & Liang, P. Evaluating Verifiability in Generative Search Engines. Findings of EMNLP, 7001-7025 (2023). doi:10.18653/v1/2023.findings-emnlp.467.

18. Zheng, L. et al. Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. Advances in Neural Information Processing Systems 36 (2023). doi:10.52202/075280-2020.

19. Liang, P. et al. Holistic Evaluation of Language Models. TMLR (2023).

20. Priem, J., Piwowar, H. & Orr, R. OpenAlex: A fully-open index of scholarly works, authors, venues, institutions, and concepts. arXiv:2205.01833 (2022).

21. Gao, L. et al. RARR: Researching and Revising What Language Models Say, Using Language Models. Proceedings of ACL, 16477-16508 (2023). doi:10.18653/v1/2023.acl-long.910.

22. Dhuliawala, S. et al. Chain-of-Verification Reduces Hallucination in Large Language Models. Findings of ACL, 3563-3578 (2024). doi:10.18653/v1/2024.findings-acl.212.

23. Xu, Z. et al. CiteCheck: Towards Accurate Citation Faithfulness Detection. arXiv:2502.10881v1 (2025).

24. Filice, S. et al. Generate but Verify: Answering with Faithfulness in RAG-based Question Answering. Proceedings of IJCNLP-AACL, 1017-1037 (2025). doi:10.18653/v1/2025.ijcnlp-long.56.

25. Debenedetti, E. et al. Defeating Prompt Injections by Design. arXiv:2503.18813v2 (2025).

26. Wang, H., Poskitt, C. M. & Sun, J. AgentSpec: Customizable Runtime Enforcement for Safe and Reliable LLM Agents. arXiv:2503.18666v1 (2025).

27. Shi, T. et al. Progent: Securing AI Agents with Privilege Control. arXiv:2504.11703v3 (2026).

28. Costa, M. et al. Securing AI Agents with Information-Flow Control. arXiv:2505.23643v2 (2025).

29. Palumbo, N. et al. Formal Policy Enforcement for Agentic Systems. arXiv:2602.16708v4 (2026).

30. Yao, S. et al. ReAct: Synergizing Reasoning and Acting in Language Models. International Conference on Learning Representations (2023).

## Figure legends

Figure 1. Release decisions across controlled component conditions. Panel a shows the original formal A/B/C comparison, with each cell reporting releases among six candidate inputs. T0 and T1 are eligible controls; T2-T7 are ineligible. Color indicates whether the observed release or withholding agrees with independent eligibility, rather than treating withholding as inherently correct. Panel b shows the separate, post hoc contemporaneous C/D comparison on the reused inputs. The additional row reports the English-coverage diagnostic for T4; the original A results are unchanged. Counts describe six fixed task templates per condition and are not independent population samples.

Figure 2. Clean generation outcomes and a fixed-score locator diagnostic. In the original formal clean runs, all final outputs were eligible. A withheld all 18; all contained legitimate Figure 2 references. C released 16 and withheld two after low upstream scores. The lower branch replays the saved A outputs after removing only the legal locator at unchanged final scores: 15 pass and three remain below the quality threshold. This branch is an offline counterfactual rather than a new generation experiment. Arrows summarize recorded decision routes and are not intended to indicate an independently estimated causal effect.

Figure 3. Mechanisms of false rejection in the original formal experiment. Panel a contrasts supported candidate values with the registry disclaimer incorrectly used as counterevidence in two component cases. Displayed explanations are concise paraphrases of the saved receipts. Panel b shows the repeated score of 88 in the two clean generation failures against the frozen threshold of 90. Their evidence verifier was never called. Exact candidates, reviews and receipts are retained in the minimum dataset.

## Table legends

Table 1. Original formal controlled outcomes. Component denominators are 36 ineligible or 12 eligible inputs per arm. Generation denominators are 18 runs per controller and condition. A dash denotes an outcome that is not estimated, rather than zero. All first-round and final generated artifacts were eligible, so there is no empirical workflow false-release denominator.

Table 2. Separate post hoc sensitivity and C/D results. A-English is evaluated on the original saved component candidates. C and D are contemporaneous new calls on reused inputs and must not be pooled with the original formal C. Locator edits hold original review scores fixed and are reported separately from live runs.

Table 3. Boundary interventions on saved C verifier receipts. The first three families each modify the same 48 receipts, comprising 12 eligible and 36 ineligible candidates; the last family covers six ineligible completed-work assertions. Total releases and ineligible releases have different denominators. Explanations are retained unchanged and may contradict the forced verdict. W is the semantic-label-only rule, not D. These constructed, correlated interventions do not estimate natural error rates or revise the original formal results.
