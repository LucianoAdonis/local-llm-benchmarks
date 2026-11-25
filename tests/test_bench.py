"""Suite runner against the in-process mock. Structure and validity logic, not timing."""
import json
import os
import tempfile
import unittest

from llmbench import PROTOCOL_VERSION, RESULT_SCHEMA
from llmbench import report
from llmbench.bench import DEPTH_CLASSES, Bench, build_suite, depth_target, grade_sanity, headline, soak_stability, tidy, verdict
from llmbench.client import EndpointError
from llmbench.mockserver import MockServer
from llmbench.sanitize import clean

FAST = {"prefill_tok_s": 400000.0, "decode_tok_s": 3000.0, "overhead_ms": 0.0}


def quiet(_line):
    return None


class SuiteDefinitionTest(unittest.TestCase):
    def test_depth_targets_fit_their_window(self):
        for label, size in DEPTH_CLASSES.items():
            target = depth_target(label)
            self.assertLess(int(target * 1.03) + 256, size * 1024, label)
            self.assertGreaterEqual(target, int(0.9 * (size * 1024 - 256)), label)

    def test_suites(self):
        self.assertEqual([s["id"] for s in build_suite("quick")], ["chat", "ctx-4k", "ctx-16k"])
        standard = [s["id"] for s in build_suite("standard")]
        self.assertEqual(standard, ["chat", "gen-long", "ctx-4k", "ctx-16k", "followup-16k", "ctx-64k", "sanity", "control"])
        self.assertIn("repeat-16k", [s["id"] for s in build_suite("deep")])
        self.assertNotIn("soak", standard)  # ten minutes of load is opt-in
        with self.assertRaises(ValueError):
            build_suite("nope")

    def test_depths_and_scenario_overrides(self):
        bench = Bench(url="http://127.0.0.1:1", suite="standard", depths=["8k", "32k"], emit=quiet)
        self.assertEqual([s["id"] for s in bench.scenarios], ["chat", "gen-long", "ctx-8k", "ctx-32k", "followup-16k", "sanity", "control"])
        bench = Bench(url="http://127.0.0.1:1", suite="quick", soak_minutes=5, runs=7, emit=quiet)
        self.assertEqual([s["id"] for s in bench.scenarios], ["chat", "ctx-4k", "ctx-16k", "soak"])
        self.assertEqual(bench.scenarios[-1]["minutes"], 5)
        self.assertEqual([s["runs"] for s in bench.scenarios[:3]], [7, 7, 7])
        bench = Bench(url="http://127.0.0.1:1", suite="standard", soak_minutes=5, runs=4, emit=quiet)
        self.assertEqual([s["id"] for s in bench.scenarios][-2:], ["soak", "control"])   # the drift check stays last
        self.assertEqual(bench.scenarios[-1]["runs"], 2)
        bench = Bench(url="http://127.0.0.1:1", suite="quick", only=["chat", "followup-4k", "parallel-2"], runs=1, emit=quiet)
        self.assertEqual([s["id"] for s in bench.scenarios], ["chat", "followup-4k", "parallel-2"])
        self.assertTrue(all(s["runs"] == 1 for s in bench.scenarios))
        with self.assertRaises(ValueError):
            Bench(url="http://127.0.0.1:1", depths=["3k"], emit=quiet)
        with self.assertRaises(ValueError):
            Bench(url="http://127.0.0.1:1", only=["warp-speed"], emit=quiet)

    def test_grade_sanity(self):
        self.assertTrue(grade_sanity("The word is cluster-7493.", {"contains": ["CLUSTER-7493"]}))
        self.assertFalse(grade_sanity("ALPHA is X1", {"contains": ["X1", "Y2"]}))
        self.assertIsNone(grade_sanity("   ", {"contains": ["X1"]}))
        self.assertTrue(grade_sanity('Here you go:\n```json\n{"status": "OK", "sum": 93.0}\n```', {"json": {"status": "ok", "sum": 93}}))
        self.assertFalse(grade_sanity('{"status": "ok", "sum": 92}', {"json": {"status": "ok", "sum": 93}}))
        self.assertFalse(grade_sanity("status ok, sum 93", {"json": {"status": "ok", "sum": 93}}))
        self.assertFalse(grade_sanity('{"status": "ok", "sum": "many"}', {"json": {"status": "ok", "sum": 93}}))

    def test_soak_stability_ratio(self):
        runs = [{"flags": [], "decode_tok_s": v, "prefill_tok_s": 1000.0} for v in (100.0, 98.0, 80.0, 90.0)]
        runs.append({"flags": ["error"], "decode_tok_s": 1.0})
        stability = soak_stability(runs)
        self.assertEqual(stability["loops"], 5)
        self.assertEqual((stability["writing"]["best"], stability["writing"]["worst"], stability["writing"]["ratio"]), (100.0, 80.0, 0.8))
        self.assertEqual(stability["reading"]["ratio"], 1.0)

    def test_tidy_rounds_floats(self):
        self.assertEqual(tidy({"a": [1.23456789012, 3]}), {"a": [1.23457, 3]})


class RunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = MockServer(cache=True, **FAST).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def bench(self, **kwargs):
        kwargs.setdefault("model", "mock-model")
        kwargs.setdefault("emit", quiet)
        return Bench(url=self.server.url, **kwargs)

    def test_unreachable_endpoint(self):
        with self.assertRaises(EndpointError):
            Bench(url="http://127.0.0.1:9", emit=quiet).run()

    def test_model_is_chosen_when_unambiguous(self):
        bench = Bench(url=self.server.url, suite="quick", emit=quiet)
        bench.prepare()
        self.assertEqual(bench.model, "mock-model")

    def test_a_model_loaded_by_the_run_itself_is_reported(self):
        from llmbench import runtimes
        original = runtimes.detect
        try:
            listing = {"name": "lmstudio", "reachable": True, "models": ["qwen-x"], "loaded_models": []}
            runtimes.detect = lambda root, api_key=None, timeout=4.0: dict(listing)
            bench = Bench(url=self.server.url, emit=quiet)
            bench.prepare()
            self.assertEqual((bench.model, bench.loaded_before), ("qwen-x", False))
            bench.context, bench.context_source = 8192, "runtime"
            note = bench._load_note()
            self.assertIn("LM Studio loaded it with its default settings (context window 8,192 tokens)", note)
            listing["loaded_models"] = ["qwen-x"]
            bench = Bench(url=self.server.url, emit=quiet)
            bench.prepare()
            self.assertIsNone(bench._load_note())
        finally:
            runtimes.detect = original
        # a runtime that only serves what it was started with never gets the note
        plain = Bench(url=self.server.url, emit=quiet)
        plain.prepare()
        self.assertIsNone(plain._load_note())

    def test_no_model_and_several_models_give_different_errors(self):
        from llmbench import runtimes
        original = runtimes.detect
        try:
            runtimes.detect = lambda root, api_key=None, timeout=4.0: {"name": "lmstudio", "reachable": True, "models": [], "loaded_models": []}
            with self.assertRaises(EndpointError) as caught:
                Bench(url=self.server.url, emit=quiet).prepare()
            self.assertIn("no chat model", str(caught.exception))
            runtimes.detect = lambda root, api_key=None, timeout=4.0: {"name": "ollama", "reachable": True, "models": ["a:latest", "b:latest"], "loaded_models": []}
            with self.assertRaises(EndpointError) as caught:
                Bench(url=self.server.url, emit=quiet).prepare()
            self.assertIn("pass --model with one of: a:latest, b:latest", str(caught.exception))
        finally:
            runtimes.detect = original

    def test_standard_suite_end_to_end(self):
        lines = []
        result = self.bench(suite="standard", context=70000, emit=lines.append, label="unit").run()
        self.assertEqual(result["schema"], RESULT_SCHEMA)
        self.assertEqual(result["tool"]["protocol"], PROTOCOL_VERSION)
        self.assertFalse(result["aborted"])
        by_id = {s["id"]: s for s in result["scenarios"]}
        self.assertEqual(list(by_id), ["chat", "gen-long", "ctx-4k", "ctx-16k", "followup-16k", "ctx-64k", "sanity", "control"])
        # the first read at each new size is made, reported, and kept out of the medians
        for sid in ("ctx-4k", "ctx-16k", "ctx-64k"):
            self.assertEqual(len(by_id[sid]["runs"]), by_id[sid]["planned_runs"])
            # The mock shares this process, so a busy machine can group arrivals; that note
            # is the only one allowed here.
            self.assertLessEqual(set(by_id[sid]["first_run"]["flags"]), {"buffered-stream"})
            self.assertIn("reading_vs_steady_pct", by_id[sid]["summary"]["first_run"])
            self.assertNotIn(by_id[sid]["first_run"]["workload"]["sha256"], [r["workload"]["sha256"] for r in by_id[sid]["runs"]])
        self.assertNotIn("first_run", by_id["followup-16k"])
        self.assertAlmostEqual(result["headline"]["drift"]["ratio"], 1.0, delta=0.5)
        for sid, record in by_id.items():
            self.assertNotIn("skipped", record, sid)
            self.assertEqual(record["summary"]["runs_valid"], record["planned_runs"], sid)
        sanity = by_id["sanity"]["summary"]
        self.assertEqual((sanity["checks_passed"], sanity["checks_total"], sanity["checks_failed"]), (3, 3, []))
        self.assertIn("3 of 3 checks passed", report.terminal(result))
        # every model gets the same number of TOKENS: prompts land within 5% of the target
        for sid in ("ctx-4k", "ctx-16k", "ctx-64k"):
            target = depth_target(by_id[sid]["depth"])
            for run in by_id[sid]["runs"]:
                self.assertLess(abs(run["prompt_tokens"] - target), 0.05 * target, sid)
                self.assertNotIn("cache-hit", run["flags"])
                self.assertEqual(run["workload"]["kind"], "diverse")
        # fresh runs use different text each time
        hashes = [run["workload"]["sha256"] for run in by_id["ctx-16k"]["runs"]]
        self.assertEqual(len(set(hashes)), len(hashes))
        # the follow-up turn reuses the cached context
        for run in by_id["followup-16k"]["runs"]:
            self.assertGreater(run["cached_tokens"], 0.9 * run["first_turn"]["prompt_tokens"])
            self.assertNotIn("no-cache-reuse", run["flags"])
            self.assertIn("cache_speedup", run)
        self.assertEqual(by_id["gen-long"]["runs"][0]["completion_tokens"], 1024)
        self.assertEqual(by_id["ctx-16k"]["runs"][0]["completion_tokens"], 256)
        head = result["headline"]
        self.assertEqual(set(head["reading_tok_s"]), {"4k", "16k", "64k"})
        # reading speed is also given in characters, the unit two different models share
        self.assertEqual(set(head["reading_chars_s"]), {"4k", "16k", "64k"})
        run = by_id["ctx-16k"]["runs"][0]
        self.assertGreater(run["prompt_chars"], 3 * run["prompt_tokens"])
        self.assertAlmostEqual(head["reading_chars_s"]["16k"] / head["reading_tok_s"]["16k"], run["prompt_chars"] / run["prompt_tokens"], delta=0.3)
        self.assertIn("chars/s at 16K", report.terminal(result))
        self.assertGreater(run["output_chars"], 0)
        self.assertEqual(set(head["request_seconds"]), {"quick_question_300_out", "code_review_16k_in_500_out", "big_read_64k_in_1000_out", "followup_16k_500_out"})
        self.assertNotEqual(result["verdict"]["status"], "invalid")
        self.assertEqual(result["settings"]["endpoint"].split(":")[0], "loopback")
        self.assertTrue(any(line.startswith("ctx-16k") for line in lines))
        # the saved form carries no address, path or host name
        text = json.dumps(clean(result))
        self.assertNotIn("127.0.0.1", text)
        self.assertNotIn(os.path.expanduser("~"), text)
        # reports render
        self.assertIn("What this means", report.terminal(result))
        self.assertIn("| ctx-16k |", report.markdown(result))
        comparison = report.compare(result, result)
        self.assertIn("within noise", comparison)
        self.assertNotIn("better", comparison)

    def test_depths_that_do_not_fit_are_skipped_with_a_reason(self):
        result = self.bench(suite="quick", context=8192, runs=1).run()
        by_id = {s["id"]: s for s in result["scenarios"]}
        self.assertNotIn("skipped", by_id["ctx-4k"])
        self.assertIn("needs a context window", by_id["ctx-16k"]["skipped"])
        self.assertIn("skipped", report.terminal(result))

    def test_unknown_context_caps_depth_at_16k(self):
        result = self.bench(suite="standard", runs=1, only=["ctx-16k", "ctx-64k"]).run()
        by_id = {s["id"]: s for s in result["scenarios"]}
        self.assertNotIn("skipped", by_id["ctx-16k"])
        self.assertIn("--context", by_id["ctx-64k"]["skipped"])

    def test_server_side_rejection_stops_deeper_scenarios(self):
        reject = dict(FAST, n_ctx=6000, context_error=True)
        result = self.bench(suite="quick", runs=1, context=200000, depths=["4k", "16k", "32k"], extra_body={"mock": reject}).run()
        by_id = {s["id"]: s for s in result["scenarios"]}
        self.assertEqual(by_id["ctx-4k"]["summary"]["runs_valid"], 1)
        self.assertIn("rejected", by_id["ctx-16k"]["skipped"])
        self.assertEqual(by_id["ctx-16k"]["runs"], [])            # the first read was refused, so nothing was measured
        self.assertIn("rejected the prompt at 16K", by_id["ctx-32k"]["skipped"])
        self.assertNotEqual(result["verdict"]["status"], "invalid")      # 4K was measured; 16K did not fit
        self.assertEqual(by_id["ctx-32k"]["runs"], [])
        self.assertNotIn("first_run", by_id["ctx-32k"])

    def test_silent_truncation_makes_the_result_invalid(self):
        truncating = dict(FAST, n_ctx=6000)
        result = self.bench(suite="quick", runs=1, only=["ctx-16k"], extra_body={"mock": truncating}).run()
        record = result["scenarios"][0]
        self.assertIn("prompt-truncated", record["runs"][0]["flags"])
        self.assertEqual(result["verdict"]["status"], "invalid")
        self.assertTrue(any("shortened the prompt" in p for p in result["verdict"]["problems"]))

    def test_repetition_probe_and_parallel(self):
        result = self.bench(suite="deep", runs=1, only=["ctx-16k", "repeat-16k", "parallel-3"]).run()
        by_id = {s["id"]: s for s in result["scenarios"]}
        self.assertEqual(by_id["repeat-16k"]["runs"][0]["workload"]["kind"], "repetitive")
        self.assertGreater(by_id["repeat-16k"]["runs"][0]["workload"]["compress_ratio"], 20)
        self.assertLess(by_id["ctx-16k"]["runs"][0]["workload"]["compress_ratio"], 8)
        self.assertEqual(set(result["headline"]["repetition_speedup"]), {"prefill_tok_s", "decode_tok_s"})
        parallel = by_id["parallel-3"]["runs"][0]
        self.assertEqual((parallel["parallel"], parallel["requests_ok"], parallel["completion_tokens"]), (3, 3, 3 * 256))
        self.assertEqual(set(result["calibration"]), {"diverse", "repetitive"})

    def test_thinking_model_still_produces_valid_numbers(self):
        thinking = dict(FAST, reasoning_tokens=100000)
        result = self.bench(suite="quick", runs=1, only=["chat", "followup-4k"], extra_body={"mock": thinking}).run()
        for record in result["scenarios"]:
            self.assertEqual(record["summary"]["runs_valid"], 1, record["id"])
            self.assertIn("reasoning-only", record["runs"][0]["flags"])
        self.assertIsNotNone(result["headline"]["writing_tok_s"])

    def test_sanity_gate_catches_a_runtime_that_drops_the_start_of_the_prompt(self):
        truncating = dict(FAST, n_ctx=1500)
        result = self.bench(suite="quick", only=["sanity"], extra_body={"mock": truncating}).run()
        record = result["scenarios"][0]
        by_check = {run["check"]: run for run in record["runs"]}
        self.assertTrue(by_check["exact-word"]["passed"])
        self.assertTrue(by_check["json"]["passed"])
        self.assertFalse(by_check["needle"]["passed"])           # the early marker was truncated away
        self.assertIn("prompt-truncated", by_check["needle"]["flags"])
        self.assertEqual(record["summary"]["checks_passed"], 2)
        self.assertTrue(any("needle" in line for line in result["verdict"]["cautions"]))

    def test_sanity_is_inconclusive_when_thinking_uses_the_whole_cap(self):
        thinking = dict(FAST, reasoning_tokens=100000)
        result = self.bench(suite="quick", only=["sanity"], extra_body={"mock": thinking}).run()
        summary = result["scenarios"][0]["summary"]
        self.assertEqual((summary["checks_passed"], summary["checks_failed"], len(summary["checks_inconclusive"])), (0, [], 3))

    def test_sanity_passes_after_thinking(self):
        result = self.bench(suite="quick", only=["sanity"], extra_body={"mock": dict(FAST, reasoning_tokens=40)}).run()
        self.assertEqual(result["scenarios"][0]["summary"]["checks_passed"], 3)

    def test_soak_loops_by_the_clock_and_reports_stability(self):
        result = self.bench(suite="quick", only=["chat"], runs=1, soak_minutes=0.01).run()
        soak = [s for s in result["scenarios"] if s["id"] == "soak"][0]
        self.assertGreaterEqual(len(soak["runs"]), 3)
        stability = soak["summary"]["stability"]
        self.assertEqual(stability["loops"], len(soak["runs"]))
        self.assertTrue(0 < stability["writing"]["ratio"] <= 1)
        self.assertIn("worst loop", report.terminal(result))

    def test_thinking_off_sends_both_request_fields_but_never_overrides_the_user(self):
        bench = self.bench(suite="quick", thinking="off")
        self.assertEqual(bench.extra_body["reasoning_effort"], "none")
        self.assertEqual(bench.extra_body["chat_template_kwargs"], {"enable_thinking": False})
        bench = self.bench(suite="quick", thinking="off", extra_body={"reasoning_effort": "low"})
        self.assertEqual(bench.extra_body["reasoning_effort"], "low")
        with self.assertRaises(ValueError):
            self.bench(suite="quick", thinking="sometimes")

    def test_a_model_id_that_is_a_file_path_never_reaches_the_result(self):
        # llama-server reports the model's full path as its id unless --alias is given.
        bench = self.bench(suite="quick", runs=1, only=["chat"], model="/Users/someone/models/secret-project/model-Q4_K_M.gguf")
        result = bench.run()
        text = json.dumps(result)
        self.assertEqual(result["model"]["id"], "model-Q4_K_M.gguf")
        self.assertNotIn("someone", text)
        self.assertNotIn("secret-project", text)
        from llmbench.bench import default_output_path
        self.assertNotIn("someone", default_output_path(result))

    def test_size_warmup_can_be_switched_off(self):
        result = self.bench(suite="quick", runs=1, only=["ctx-4k"], size_warmup=False).run()
        self.assertNotIn("first_run", result["scenarios"][0])
        self.assertFalse(result["settings"]["size_warmup"])

    def test_drift_is_reported_as_a_caution(self):
        from llmbench.bench import headline as make_headline
        def chatlike(sid, rate):
            return {"id": sid, "kind": "chat", "runs": [], "summary": {"runs_total": 2, "runs_valid": 2, "flags": {}, "decode_tok_s": {"n": 2, "median": rate, "min": rate, "max": rate, "spread_pct": 0.0}, "ttft_s": {"n": 2, "median": 0.2, "min": 0.2, "max": 0.2, "spread_pct": 0.0}}}
        result = {"scenarios": [chatlike("chat", 100.0), chatlike("control", 80.0)], "state_before": {}, "state_after": {}}
        result["headline"] = make_headline(result)
        self.assertAlmostEqual(result["headline"]["drift"]["ratio"], 0.8)
        cautions = verdict(result)["cautions"]
        self.assertTrue(any("80% of the start" in line for line in cautions), cautions)
        steady = {"scenarios": [chatlike("chat", 100.0), chatlike("control", 97.0)], "state_before": {}, "state_after": {}}
        steady["headline"] = make_headline(steady)
        self.assertEqual(verdict(steady)["status"], "clean")

    def test_file_corpus(self):
        with tempfile.TemporaryDirectory() as folder:
            for index in range(6):
                with open(os.path.join(folder, "mod_%d.py" % index), "w", encoding="utf-8") as handle:
                    handle.write("\n".join("def f_%d_%d(x):\n    return x + %d" % (index, i, i) for i in range(300)))
            result = self.bench(suite="quick", runs=1, only=["ctx-4k"], corpus="file:" + folder).run()
            run = result["scenarios"][0]["runs"][0]
            self.assertEqual(run["workload"]["kind"], "file")
            self.assertNotIn(folder, json.dumps(result))
            self.assertEqual(result["settings"]["corpus"], "file")

    def test_headline_and_verdict_tolerate_empty_results(self):
        empty = {"scenarios": [], "state_before": {}, "state_after": {}}
        self.assertEqual(headline(empty)["request_seconds"], {})
        self.assertEqual(verdict(empty)["status"], "invalid")          # nothing was measured
        self.assertIn("nothing was measured", verdict(empty)["problems"])
        self.assertEqual(verdict(dict(empty, aborted=True))["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
