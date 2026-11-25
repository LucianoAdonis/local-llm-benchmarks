"""Client behavior against the in-process mock. Logic only: timing accuracy is checked by
``llmbench selftest``, which runs the mock in a separate process."""
import unittest

from llmbench.client import _TextAccounting, get_json, post_json, split_base_url, stream_chat
from llmbench.mockserver import MockServer, count_tokens, expected_timing, flatten

FAST = {"prefill_tok_s": 500000.0, "decode_tok_s": 4000.0, "overhead_ms": 0.0}
MESSAGES = [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hello " * 200}]


def blank():
    return {"first_answer_s": None, "answer_events": 0, "answer_chars": 0, "reasoning_events": 0, "reasoning_chars": 0, "inline_think": False}


class UrlTest(unittest.TestCase):
    def test_accepts_common_forms(self):
        for url in ("http://127.0.0.1:1234", "http://127.0.0.1:1234/", "http://127.0.0.1:1234/v1", "http://127.0.0.1:1234/v1/chat/completions", "127.0.0.1:1234"):
            self.assertEqual(split_base_url(url), ("http://127.0.0.1:1234", "/v1/chat/completions"), url)

    def test_keeps_a_path_prefix(self):
        self.assertEqual(split_base_url("https://host.example/proxy/v1")[0], "https://host.example/proxy")


class TextAccountingTest(unittest.TestCase):
    def feed(self, pieces):
        out = blank()
        accounting = _TextAccounting(out)
        for index, (answer, reasoning) in enumerate(pieces):
            accounting.add(float(index + 1), answer, reasoning)
        return out, accounting.finish()

    def test_plain_answer(self):
        out, kept = self.feed([("Hello", ""), (" world", "")])
        self.assertEqual((out["answer_events"], out["reasoning_events"], out["first_answer_s"]), (2, 0, 1.0))
        self.assertEqual(kept, "Hello world")

    def test_separate_reasoning_field(self):
        out, kept = self.feed([("", "hmm"), ("", " ok"), ("Answer", "")])
        self.assertEqual((out["answer_events"], out["reasoning_events"], out["first_answer_s"]), (1, 2, 3.0))
        self.assertEqual(kept, "Answer")
        self.assertFalse(out["inline_think"])

    def test_inline_think_block(self):
        out, kept = self.feed([("<think>", ""), ("plan", ""), ("</think>", ""), ("Answer", ""), (" done", "")])
        self.assertTrue(out["inline_think"])
        self.assertEqual((out["reasoning_events"], out["answer_events"], out["first_answer_s"]), (3, 2, 4.0))
        self.assertEqual(kept, "Answer done")

    def test_inline_think_tag_split_across_events_with_leading_newline(self):
        out, kept = self.feed([("\n", ""), ("<th", ""), ("ink>plan", ""), (" more</think>", ""), ("Answer", "")])
        self.assertTrue(out["inline_think"])
        self.assertEqual((out["reasoning_events"], out["answer_events"], out["first_answer_s"]), (4, 1, 5.0))
        self.assertEqual(kept, "Answer")

    def test_leading_whitespace_then_answer_is_all_answer(self):
        out, kept = self.feed([("\n", ""), ("Hi", "")])
        self.assertEqual((out["reasoning_events"], out["answer_events"], out["first_answer_s"]), (0, 2, 1.0))
        self.assertEqual(kept, "\nHi")

    def test_less_than_sign_that_is_not_a_think_tag(self):
        out, _ = self.feed([("<", ""), ("div>", "")])
        self.assertEqual((out["reasoning_events"], out["answer_events"]), (0, 2))

    def test_whole_think_block_in_one_buffered_event(self):
        out, kept = self.feed([("<think>plan</think>", ""), ("Answer", "")])
        self.assertEqual((out["reasoning_events"], out["answer_events"], out["first_answer_s"]), (1, 1, 2.0))
        self.assertEqual(kept, "Answer")

    def test_stream_that_ends_while_undecided(self):
        out, kept = self.feed([("\n", "")])
        self.assertEqual((out["answer_events"], kept), (1, "\n"))


class StreamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = MockServer(**FAST).start()
        cls.url = cls.server.url + "/v1/chat/completions"

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def ask(self, max_tokens=40, messages=None, **mock):
        return stream_chat(self.url, {"model": "mock-model", "messages": messages or MESSAGES, "max_tokens": max_tokens, "mock": mock}, timeout=20)

    def test_plain_stream(self):
        out = self.ask()
        self.assertIsNone(out["error"])
        self.assertEqual(out["http_status"], 200)
        self.assertTrue(out["saw_done"])
        self.assertEqual(out["finish_reason"], "length")
        self.assertEqual((out["text_events"], out["answer_events"], out["reasoning_events"]), (40, 40, 0))
        self.assertEqual(out["usage"]["completion_tokens"], 40)
        self.assertEqual(out["usage"]["prompt_tokens"], count_tokens(flatten(MESSAGES)) + 4 * len(MESSAGES) + 3)
        self.assertEqual(out["first_token_s"], out["first_answer_s"])
        self.assertLessEqual(out["first_token_s"], out["last_token_s"])
        self.assertLessEqual(out["last_token_s"], out["wall_s"])
        self.assertEqual(len(out["answer_text"]), out["answer_chars"])
        self.assertIsNotNone(out["gap_median_ms"])

    def test_role_only_frame_is_not_a_token(self):
        # The mock sends a role frame immediately; first_event precedes first_token.
        out = self.ask(prefill_tok_s=2000.0)
        self.assertLess(out["first_event_s"], out["first_token_s"])

    def test_reasoning_fields(self):
        for field in ("reasoning_content", "reasoning"):
            out = self.ask(reasoning_tokens=15, reasoning_field=field)
            self.assertEqual((out["reasoning_events"], out["answer_events"]), (15, 25), field)
            self.assertLess(out["first_token_s"], out["first_answer_s"])
            self.assertFalse(out["inline_think"])

    def test_inline_think(self):
        out = self.ask(reasoning_tokens=15, reasoning_field="inline")
        self.assertTrue(out["inline_think"])
        self.assertEqual((out["reasoning_events"], out["answer_events"]), (15, 25))
        self.assertNotIn("think>", out["answer_text"])

    def test_reasoning_only(self):
        out = self.ask(reasoning_tokens=1000)
        self.assertIsNone(out["error"])
        self.assertIsNone(out["first_answer_s"])
        self.assertEqual(out["reasoning_events"], 40)

    def test_buffered_stream(self):
        out = self.ask(max_tokens=64, chunk_tokens=16)
        self.assertEqual(out["text_events"], 4)
        self.assertEqual(out["usage"]["completion_tokens"], 64)
        self.assertGreater(out["first_event_chars"], 40)

    def test_usage_can_be_absent(self):
        out = self.ask(include_usage=False)
        self.assertIsNone(out["usage"])
        self.assertIsNone(out["error"])

    def test_engine_timings_are_captured(self):
        out = self.ask(include_timings=True)
        self.assertEqual(out["timings"]["predicted_n"], 40)
        self.assertIn("cache_n", out["timings"])

    def test_http_error_is_reported_not_raised(self):
        out = self.ask(n_ctx=50, context_error=True)
        self.assertEqual(out["http_status"], 400)
        self.assertIn("exceeds the available context size", out["error"])

    def test_connection_refused_is_reported_not_raised(self):
        out = stream_chat("http://127.0.0.1:9/v1/chat/completions", {"model": "x", "messages": MESSAGES}, timeout=2)
        self.assertIn("connection failed", out["error"])
        self.assertIsNotNone(out["wall_s"])

    def test_prefix_cache_reports_cached_tokens(self):
        messages = [{"role": "user", "content": "unique-prefix-cache-test " + "word " * 300}]
        self.ask(messages=messages, cache=True)
        again = self.ask(messages=messages, cache=True)
        self.assertGreater(again["usage"]["prompt_tokens_details"]["cached_tokens"], 0.9 * again["usage"]["prompt_tokens"])
        other = self.ask(messages=[{"role": "user", "content": "different start " + "word " * 300}], cache=True)
        self.assertLess(other["usage"]["prompt_tokens_details"]["cached_tokens"], 10)

    def test_non_streaming_helpers(self):
        status, body = get_json(self.server.url + "/v1/models")
        self.assertEqual((status, body["data"][0]["id"]), (200, "mock-model"))
        status, body, elapsed = post_json(self.url, {"model": "mock-model", "messages": MESSAGES, "max_tokens": 1, "mock": FAST})
        self.assertEqual(status, 200)
        self.assertEqual(body["usage"]["completion_tokens"], 1)
        self.assertGreaterEqual(elapsed, 0.0)
        self.assertEqual(get_json("http://127.0.0.1:9/v1/models", timeout=1)[0], 0)


class MockTruthTest(unittest.TestCase):
    def test_expected_timing_arithmetic(self):
        config = {"prefill_tok_s": 1000.0, "decode_tok_s": 50.0, "overhead_ms": 100.0, "chunk_tokens": 10}
        truth = expected_timing(config, 2000, 100)
        self.assertAlmostEqual(truth["first_token_s"], 0.1 + 2.0 + 0.02)
        self.assertAlmostEqual(truth["first_event_s"], truth["first_token_s"] + 9 / 50.0)
        self.assertAlmostEqual(truth["last_token_s"], truth["first_token_s"] + 99 / 50.0)


if __name__ == "__main__":
    unittest.main()
