"""Offline paired-controller and workflow-boundary tests, not study results."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for folder in ("src", "tools", "tests"):
    sys.path.insert(0, str(ROOT / folder))

from evaluate_release_case import compare, read_input
from prepare_release_study import build_plan, prepare
from release_study_runtime import authorized_text, install, release_revision_feedback
from selective_release import Candidate, Corpus, ReleasePolicy, SelectiveController, VERIFIER_SCHEMA
from test_selective_release import candidate, corpus_document, receipt
from smoke_release_verifier import integration_passed


class LiveCheckResultTests(unittest.TestCase):
    def test_malformed_negative_receipt_is_not_a_successful_defense(self):
        decision = {"plan_status": "in_progress", "evidence_check": "not_authorized",
                    "errors": ["invalid_verification_receipt:unknown evidence verdict"]}
        self.assertFalse(integration_passed(decision, "in_progress"))

    def test_api_failure_is_not_a_successful_defense(self):
        decision = {"plan_status": "in_progress", "evidence_check": "unavailable",
                    "errors": ["verification_unavailable:TimeoutError"]}
        self.assertFalse(integration_passed(decision, "in_progress"))

    def test_expected_valid_decisions_pass(self):
        positive = {"plan_status": "validated", "evidence_check": "passed", "errors": []}
        negative = {"plan_status": "in_progress", "evidence_check": "not_authorized",
                    "errors": ["u0001:unsupported_or_uncertain_premise"]}
        self.assertTrue(integration_passed(positive, "validated"))
        self.assertTrue(integration_passed(negative, "in_progress"))
        self.assertFalse(integration_passed(negative, "validated"))


class StudyPlanTests(unittest.TestCase):
    def config(self):
        return json.loads((ROOT / "robustness/configs/selective_release_6.json").read_text(encoding="utf-8"))

    def test_six_question_counts_and_pairing(self):
        plan = build_plan(self.config())
        self.assertEqual(len(plan["component"]), 144)
        self.assertEqual(len(plan["workflow"]), 72)
        self.assertEqual(len({row["input"] for row in plan["component"]}), 48)
        self.assertEqual({row["controller"] for row in plan["workflow"]}, {"A", "C"})

    def test_randomization_is_reproducible(self):
        self.assertEqual(build_plan(self.config()), build_plan(self.config()))

    def test_four_question_fallback_requires_reason(self):
        config = self.config()
        config["questions"] = [config["questions"][i] for i in (0, 1, 2, 4)]
        with self.assertRaisesRegex(ValueError, "budget reason"):
            build_plan(config)
        config["budget_reason"] = "Prespecified staffing limit, before formal execution."
        plan = build_plan(config)
        self.assertEqual(len(plan["component"]), 96)
        self.assertEqual(len(plan["workflow"]), 48)

    def test_prepare_never_claims_formal_readiness_or_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "study"
            prepare(self.config(), output)
            readiness = json.loads((output / "readiness.json").read_text())
            self.assertFalse(readiness["formal_ready"])
            self.assertEqual(readiness["completed_formal_runs"], 0)
            with self.assertRaises(FileExistsError):
                prepare(self.config(), output)

    def test_pending_template_cannot_be_run_as_formal(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "case.json"
            path.write_text(json.dumps({"schema_version": 1,
                                       "material_status": "pending_independent_review"}))
            with self.assertRaisesRegex(ValueError, "independently reviewed"):
                read_input(path)


class ControllerComparisonTests(unittest.TestCase):
    def compare(self, obj=None, response=None, override=None):
        return compare(obj or candidate(), Corpus(corpus_document()), ReleasePolicy(),
                       Mock(return_value=receipt() if response is None else response),
                       passed_override=override)

    def test_positive_and_always_block_control(self):
        decisions = self.compare()
        self.assertEqual([decisions[arm]["plan_status"] for arm in "ABC"],
                         ["validated", "in_progress", "validated"])

    def test_legal_locator_exposes_original_gate_false_rejection(self):
        obj = candidate(
            "Figure 2 reports a signal increase under the stated measurement conditions.\n"
            "We propose to test whether the effect persists under a new measurement condition."
        )
        decisions = self.compare(obj)
        self.assertEqual([decisions[arm]["plan_status"] for arm in "ABC"],
                         ["in_progress", "in_progress", "validated"])

    def test_override_cannot_substitute_for_grounded_evidence_in_C(self):
        response = receipt()
        response["units"][0].update(support=[], verdict="unsupported")
        decisions = self.compare(response=response, override=True)
        self.assertEqual([decisions[arm]["plan_status"] for arm in "ABC"],
                         ["validated", "in_progress", "in_progress"])

    def test_low_scores_do_not_pass_C_under_passed_override(self):
        obj = candidate()
        obj = Candidate(obj.text, 10, 0, obj.dimensions)
        decisions = self.compare(obj, override=True)
        self.assertEqual(decisions["A"]["plan_status"], "validated")
        self.assertEqual(decisions["C"]["plan_status"], "in_progress")


class WorkflowBoundaryTests(unittest.TestCase):
    def test_rejection_feedback_is_current_and_does_not_supply_approval(self):
        obj = candidate()
        response = receipt()
        response["units"][0]["support"] = []
        report = SelectiveController(Corpus(corpus_document()), Mock(return_value=response),
                                     ReleasePolicy()).assess(obj)
        state = {"hypothesis": obj.text, "release_authorization": report}
        self.assertIn("unsupported_or_uncertain_premise", release_revision_feedback(state))
        self.assertEqual(release_revision_feedback({**state, "hypothesis": "new text"}), "")
        report["plan_status"] = "validated"
        self.assertEqual(release_revision_feedback(state), "")

    def test_authorization_is_bound_to_plan_scores_and_corpus(self):
        corpus = Corpus(corpus_document())
        policy = ReleasePolicy()
        obj = candidate()
        report = SelectiveController(corpus, Mock(return_value=receipt()), policy).assess(obj)
        state = {
            "plan_status": "validated", "hypothesis": obj.text, "approved_hypothesis": obj.text,
            "hypothesis_score": obj.hypothesis_score, "data_score": obj.evidence_score,
            "dimensions": obj.dimensions, "release_authorization": report,
            "best_hypothesis": "A different unverified historical best.",
        }
        self.assertTrue(authorized_text(state, policy, corpus))
        for key, value in (("hypothesis", "changed"), ("approved_hypothesis", "changed"),
                           ("hypothesis_score", 96), ("data_score", 90)):
            altered = {**state, key: value}
            self.assertFalse(authorized_text(altered, policy, corpus))
        changed = corpus_document()
        changed["sources"][0]["passages"][0]["text"] += " A new observation."
        self.assertFalse(authorized_text(state, policy, Corpus(changed)))

    def test_full_graph_override_is_separate_from_verifier_and_final_text(self):
        import tools
        import search_papers
        import search_web
        import search_crossref
        import citation_checker
        import data_source_checker
        from contextlib import ExitStack
        from langgraph.graph import END

        observed = []

        def json_client(prompt, system="", schema=None, max_retries=3):
            observed.append(schema)
            if schema == VERIFIER_SCHEMA:
                return receipt()
            return {"hypothesis_score": 80, "data_score": 70, "dimensions": candidate().dimensions}

        fake = SimpleNamespace(
            json_chat=json_client, REVIEW_SCHEMA={"review": "schema"}, REVIEW_SYSTEM="main reviewer",
            MAX_ROUNDS=10, CONVERGE_PATIENCE=3, END=END,
            floor_for=lambda target: 75, novelty_floor_for=lambda target: 50,
            call_llm=lambda state: {}, call_tool_node=lambda state: {},
            knowledge_integration=lambda state: {}, parse_papers=lambda state: {},
            frontier_scan_node=lambda state: {}, gap_analysis=lambda state: {},
            hypothesis_gen=lambda state: {"hypothesis": candidate().text},
            route=lambda state: "gap", route_review=lambda state: "verify",
            build_final_delivery=lambda state: "OLD " + state.get("best_hypothesis", ""),
            build_revision_prompt=lambda state, *args, **kwargs: "Existing revision prompt",
        )

        def review(state):
            values = fake.json_chat("review input", system=fake.REVIEW_SYSTEM, schema=fake.REVIEW_SCHEMA)
            return {
                "hypothesis_score": values["hypothesis_score"], "data_score": values["data_score"],
                "dimensions": values["dimensions"], "rounds": 1, "plan_status": "validated",
                "best_hypothesis": "UNVERIFIED_HISTORICAL_VERSION",
                "score_history": [{"round": 1, "hypothesis_score": values["hypothesis_score"],
                                   "data_score": values["data_score"], "tree_version": 1}],
            }

        fake.review_hypothesis = review
        fake.data_verify = lambda state: {"final_answer": fake.build_final_delivery(state)}
        patches = (
            (search_papers, "search_papers"), (search_papers, "search_recent_papers"),
            (search_papers, "fallback_search"), (search_papers, "paper_to_dict"),
            (search_web, "search_web"), (search_crossref, "fetch_work"),
            (citation_checker, "write_citation_report"), (data_source_checker, "write_data_source_report"),
        )
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            for module, name in patches:
                stack.enter_context(patch.object(module, name, getattr(module, name)))
            stack.enter_context(patch.object(tools, "_TOOLS", copy.deepcopy(tools._TOOLS)))
            counts = install(fake, Corpus(corpus_document()), ReleasePolicy(), "C", True, folder)
            result = fake.graph.invoke({"question": "Synthetic integration fixture", "rounds": 0})
            self.assertEqual(result["hypothesis_score"], 100)
            self.assertEqual(counts["review_overrides"], 1)
            self.assertEqual(counts["verifier_calls"], 1)
            self.assertEqual(result["plan_status"], "validated")
            self.assertIn(candidate().text, result["final_answer"])
            self.assertNotIn("UNVERIFIED_HISTORICAL_VERSION", result["final_answer"])
            self.assertEqual(result["best_hypothesis"], "UNVERIFIED_HISTORICAL_VERSION")
            self.assertEqual(observed, [fake.REVIEW_SCHEMA, VERIFIER_SCHEMA])
            rejected = copy.deepcopy(result)
            rejected["release_authorization"].update(plan_status="in_progress",
                                                    errors=["u0001:unsupported_or_uncertain_premise"])
            self.assertIn("unsupported_or_uncertain_premise",
                          fake.build_revision_prompt(rejected, "gap", "papers"))
            self.assertEqual(fake.build_revision_prompt(result, "gap", "papers"),
                             "Existing revision prompt")
            retrieved = search_papers.search_papers("signal", per_page=5)
            self.assertEqual(len(retrieved), 1)
            self.assertNotIn("recall", tools._TOOLS)
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                search_crossref.fetch_work("10.1/missing")


if __name__ == "__main__":
    unittest.main()
