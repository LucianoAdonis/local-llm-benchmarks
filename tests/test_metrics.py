import unittest

from llmbench.metrics import (
    chance_threshold_pct,
    client_decode_rate,
    compare_stats,
    derive_run,
    fit_reading,
    meaningful_spread,
    normalize_engine,
    request_time,
    run_is_valid,
    stability,
    summarize,
    summarize_runs,
)


def stream(**overrides):
    base = {
        "error": None, "first_token_s": 1.0, "first_answer_s": 1.0, "last_token_s": 2.0, "wall_s": 2.01,
        "text_events": 101, "answer_events": 101, "reasoning_events": 0, "answer_chars": 505, "reasoning_chars": 0,
        "first_event_chars": 5, "finish_reason": "length", "saw_done": True,
        "usage": {"prompt_tokens": 4000, "completion_tokens": 101}, "timings": None, "stats": None,
    }
    base.update(overrides)
    return base


class DecodeRateTest(unittest.TestCase):
    def test_per_token_stream_uses_n_minus_one_intervals(self):
        out = client_decode_rate(101, 101, 5, 505, 1.0)
        self.assertAlmostEqual(out["decode_tok_s"], 100.0, places=6)
        self.assertEqual(out["stream_granularity"], 1.0)

    def test_v1_formula_would_overstate(self):
        # v1 divided all N tokens by the window: 101 tok/s here, and far worse when buffered.
        self.assertGreater(101 / 1.0, client_decode_rate(101, 101, 5, 505, 1.0)["decode_tok_s"])

    def test_buffered_stream_excludes_the_first_chunk(self):
        # 160 tokens flushed 16 at a time at a true 80 tok/s: first event at token 16,
        # last at token 160, so the window covers 144 tokens in 1.8 s.
        out = client_decode_rate(160, 10, 80, 800, 1.8)
        self.assertAlmostEqual(out["decode_tok_s"], 80.0, places=6)
        self.assertEqual(out["stream_granularity"], 0.062)

    def test_single_event_has_no_rate(self):
        out = client_decode_rate(100, 1, 500, 500, 0.0)
        self.assertIsNone(out["decode_tok_s"])

    def test_missing_token_count_falls_back_to_events(self):
        out = client_decode_rate(None, 51, 5, 255, 1.0)
        self.assertAlmostEqual(out["decode_tok_s"], 50.0, places=6)


class DeriveRunTest(unittest.TestCase):
    def test_clean_run(self):
        run = derive_run(stream(), max_tokens=101, expect_fresh=True, target_prompt_tokens=4000, estimated_prompt_tokens=4000)
        self.assertEqual(run["flags"], [])
        self.assertAlmostEqual(run["decode_tok_s"], 100.0, places=6)
        # first token at 1.0 s, of which 1/100 s was spent writing that token
        self.assertAlmostEqual(run["prefill_tok_s"], 4000.0 / 0.99, places=6)
        self.assertEqual(run["decode_source"], "client")
        self.assertTrue(run_is_valid(run))

    def test_buffered_stream_does_not_understate_reading_speed(self):
        # True speeds: read 4,000 tokens in 2.0 s, write 80 tok/s, flush every 16 tokens.
        # First event at 2.0 + 16/80 = 2.2 s; last (token 160) at 2.0 + 160/80 = 4.0 s.
        buffered = stream(first_token_s=2.2, first_answer_s=2.2, last_token_s=4.0, wall_s=4.0, text_events=10, answer_events=10, answer_chars=800, first_event_chars=80,
                          usage={"prompt_tokens": 4000, "completion_tokens": 160})
        run = derive_run(buffered, max_tokens=160, expect_fresh=True)
        self.assertAlmostEqual(run["decode_tok_s"], 80.0, places=6)
        self.assertAlmostEqual(run["prefill_tok_s"], 2000.0, places=6)
        self.assertEqual(run["ttft_s"], 2.2)  # what the user waited is reported unchanged
        self.assertIn("buffered-stream", run["flags"])

    def test_thinking_tokens_count_towards_writing_speed(self):
        # 60 thinking tokens then 41 answer tokens at 100 tok/s. Answer starts at 1.6 s.
        run = derive_run(stream(first_answer_s=1.6, reasoning_events=60, answer_events=41, reasoning_chars=300, answer_chars=205), max_tokens=101, expect_fresh=True)
        self.assertAlmostEqual(run["decode_tok_s"], 100.0, places=6)
        self.assertEqual(run["ttft_s"], 1.0)
        self.assertEqual(run["ttfa_s"], 1.6)
        self.assertTrue(run["reasoning_seen"])

    def test_reasoning_only_is_valid_but_labelled(self):
        run = derive_run(stream(first_answer_s=None, answer_events=0, reasoning_events=101, answer_chars=0, reasoning_chars=505), max_tokens=101, expect_fresh=True)
        self.assertIn("reasoning-only", run["flags"])
        self.assertTrue(run_is_valid(run))
        self.assertIsNotNone(run["decode_tok_s"])

    def test_cache_hit_invalidates_a_fresh_run(self):
        usage = {"prompt_tokens": 4000, "completion_tokens": 101, "prompt_tokens_details": {"cached_tokens": 3900}}
        run = derive_run(stream(usage=usage), max_tokens=101, expect_fresh=True)
        self.assertIn("cache-hit", run["flags"])
        self.assertFalse(run_is_valid(run))
        self.assertEqual(run["fresh_prompt_tokens"], 100)
        self.assertIsNone(run["prefill_tok_s"])  # 100 tokens over fixed overhead is not a rate

    def test_small_shared_prefix_is_not_a_cache_hit(self):
        usage = {"prompt_tokens": 4000, "completion_tokens": 101, "prompt_tokens_details": {"cached_tokens": 30}}
        run = derive_run(stream(usage=usage), max_tokens=101, expect_fresh=True)
        self.assertNotIn("cache-hit", run["flags"])

    def test_followup_without_reuse_is_flagged(self):
        usage = {"prompt_tokens": 4000, "completion_tokens": 101, "prompt_tokens_details": {"cached_tokens": 0}}
        run = derive_run(stream(usage=usage), max_tokens=101, expect_fresh=False, expect_cache=True)
        self.assertIn("no-cache-reuse", run["flags"])
        self.assertTrue(run_is_valid(run))

    def test_truncation_and_depth_miss(self):
        truncated = derive_run(stream(usage={"prompt_tokens": 2000, "completion_tokens": 101}), max_tokens=101, expect_fresh=True, target_prompt_tokens=16000, estimated_prompt_tokens=16000)
        self.assertIn("prompt-truncated", truncated["flags"])
        self.assertFalse(run_is_valid(truncated))
        off = derive_run(stream(usage={"prompt_tokens": 4400, "completion_tokens": 101}), max_tokens=101, expect_fresh=True, target_prompt_tokens=4000, estimated_prompt_tokens=4000)
        self.assertIn("depth-miss", off["flags"])
        self.assertTrue(run_is_valid(off))

    def test_short_output_and_overflow(self):
        run = derive_run(stream(usage={"prompt_tokens": 4000, "completion_tokens": 20}, text_events=20, answer_events=20, answer_chars=100, finish_reason="stop"), max_tokens=256, expect_fresh=True, context_tokens=4096)
        self.assertIn("short-output", run["flags"])
        self.assertIn("context-overflow", run["flags"])
        self.assertNotIn("usage-undercount", run["flags"])

    def test_more_events_than_counted_tokens_is_an_undercount(self):
        run = derive_run(stream(usage={"prompt_tokens": 4000, "completion_tokens": 20}), max_tokens=101, expect_fresh=True)
        self.assertIn("usage-undercount", run["flags"])
        self.assertEqual(run["completion_tokens"], 101)

    def test_missing_usage(self):
        run = derive_run(stream(usage=None), max_tokens=101, expect_fresh=True, estimated_prompt_tokens=4100)
        self.assertIn("no-usage", run["flags"])
        self.assertEqual(run["prompt_tokens"], 4100)
        self.assertEqual(run["prompt_tokens_source"], "estimate")
        self.assertEqual(run["completion_tokens"], 101)

    def test_engine_timings_win_and_cache_n_is_read(self):
        timings = {"prompt_n": 3970, "prompt_ms": 400.0, "predicted_n": 101, "predicted_ms": 505.0, "cache_n": 30}
        run = derive_run(stream(timings=timings), max_tokens=101, expect_fresh=True)
        self.assertEqual(run["decode_source"], "engine")
        self.assertAlmostEqual(run["decode_tok_s"], 200.0, places=6)
        self.assertAlmostEqual(run["prefill_tok_s"], 9925.0, places=6)
        self.assertEqual(run["cached_tokens"], 30)
        self.assertEqual(run["cached_tokens_source"], "timings")
        self.assertIsNotNone(run["client_decode_tok_s"])

    def test_engine_prefill_over_a_few_tokens_is_dropped(self):
        timings = {"prompt_n": 17, "prompt_ms": 300.0, "predicted_n": 101, "predicted_ms": 505.0, "cache_n": 3983}
        run = derive_run(stream(timings=timings), max_tokens=101, expect_fresh=False, expect_cache=True)
        self.assertIsNone(run["engine_prefill_tok_s"])

    def test_error_run(self):
        run = derive_run({"error": "HTTP 400: too long", "wall_s": 0.1}, max_tokens=10, expect_fresh=True)
        self.assertEqual(run["flags"], ["error"])
        self.assertFalse(run_is_valid(run))

    def test_lmstudio_style_stats(self):
        engine = normalize_engine({"stats": {"tokens_per_second": 42.5, "time_to_first_token": 0.3}})
        self.assertEqual(engine["source"], "stats")
        self.assertEqual(engine["decode_tok_s"], 42.5)


class StatsTest(unittest.TestCase):
    def test_summarize(self):
        stats = summarize([10.0, 12.0, 11.0, None])
        self.assertEqual(stats["n"], 3)
        self.assertEqual(stats["median"], 11.0)
        self.assertAlmostEqual(stats["spread_pct"], 100.0 * 1.0 / 11.0)
        self.assertIsNone(summarize([None]))
        self.assertNotIn("stdev", summarize([5.0]))

    def test_summary_ignores_invalid_runs(self):
        good = derive_run(stream(), max_tokens=101, expect_fresh=True)
        bad = derive_run({"error": "boom", "wall_s": 0.1}, max_tokens=101, expect_fresh=True)
        summary = summarize_runs([good, bad])
        self.assertEqual((summary["runs_total"], summary["runs_valid"]), (2, 1))
        self.assertEqual(summary["flags"], {"error": 1})
        self.assertEqual(summary["decode_source"], "client")

    def test_stability_labels(self):
        self.assertEqual(stability(summarize([100, 101, 102])), "stable")
        self.assertEqual(stability(summarize([100, 110, 120])), "noisy")
        self.assertEqual(stability(summarize([100, 150, 200])), "unstable")
        self.assertEqual(stability(summarize([100])), "single run")
        self.assertEqual(stability(None), "no data")

    def test_millisecond_wobble_is_not_instability(self):
        stats = summarize([0.030, 0.040, 0.050])
        self.assertEqual(meaningful_spread(stats, "ttft_s"), 0.0)
        self.assertEqual(stability(stats, "ttft_s"), "stable")
        self.assertEqual(stability(summarize([1.0, 1.5, 2.0]), "ttft_s"), "unstable")

    def test_compare_requires_change_beyond_noise(self):
        base, same = summarize([100, 102, 104]), summarize([101, 103, 105])
        self.assertEqual(compare_stats("decode_tok_s", base, same)["verdict"], "within noise")
        faster = summarize([120, 121, 122])
        self.assertEqual(compare_stats("decode_tok_s", base, faster)["verdict"], "better")
        self.assertEqual(compare_stats("ttft_s", summarize([2.0, 2.02, 2.04]), summarize([3.0, 3.02, 3.04]))["verdict"], "worse")
        single = compare_stats("decode_tok_s", summarize([100]), summarize([130]))
        self.assertIn("single run", single["verdict"])
        self.assertIsNone(compare_stats("decode_tok_s", None, base))

    def test_three_noisy_runs_cannot_show_a_small_difference(self):
        # Runs that vary by about 5% on each side, medians 6% apart: the old rule (gap larger
        # than half the range) called this "better" in more than one comparison in five when
        # there was no difference at all.
        base, new = summarize([95.0, 100.0, 105.0]), summarize([101.0, 106.0, 111.0])
        result = compare_stats("decode_tok_s", base, new)
        self.assertEqual(result["verdict"], "within noise")
        self.assertGreater(result["noise_pct"], 6.0)
        self.assertEqual(result["runs"], [3, 3])
        # the same medians with tight runs are a real difference
        tight = compare_stats("decode_tok_s", summarize([99.5, 100.0, 100.5]), summarize([105.5, 106.0, 106.5]))
        self.assertEqual(tight["verdict"], "better")
        # more runs lower the bar
        many_a, many_b = summarize([95.0, 97.0, 99.0, 100.0, 101.0, 103.0, 105.0, 100.0]), summarize([103.0, 105.0, 107.0, 108.0, 109.0, 111.0, 113.0, 108.0])
        self.assertEqual(compare_stats("decode_tok_s", many_a, many_b)["verdict"], "better")

    def test_chance_threshold(self):
        self.assertIsNone(chance_threshold_pct(summarize([100]), summarize([100, 101])))
        self.assertEqual(chance_threshold_pct(summarize([100, 100, 100]), summarize([100, 100, 100])), 0.0)
        three = chance_threshold_pct(summarize([95.0, 100.0, 105.0]), summarize([95.0, 100.0, 105.0]))
        eight = chance_threshold_pct(summarize([95.0, 100.0, 105.0, 98.0, 102.0, 100.0, 97.0, 103.0]), summarize([95.0, 100.0, 105.0, 98.0, 102.0, 100.0, 97.0, 103.0]))
        self.assertGreater(three, 2 * eight)

    def test_single_run_against_several_uses_their_whole_range(self):
        several = summarize([96.0, 100.0, 104.0])   # range 8% of the median
        self.assertEqual(compare_stats("decode_tok_s", several, summarize([107.0]))["verdict"], "within noise")
        self.assertIn("single run", compare_stats("decode_tok_s", several, summarize([112.0]))["verdict"])

    def test_request_time(self):
        self.assertAlmostEqual(request_time(2.0, 50.0, 500), 12.0)
        self.assertIsNone(request_time(None, 50.0, 500))




class EngineAndHiddenTokenTest(unittest.TestCase):
    def test_runtime_stated_rate_is_used(self):
        # llama.cpp since August 2026: predicted_per_second = (n - 1) / predicted_ms
        timings = {"prompt_n": 4000, "prompt_ms": 400.0, "predicted_n": 101, "predicted_ms": 1000.0, "predicted_per_second": 100.0, "cache_n": 0}
        run = derive_run(stream(timings=timings), max_tokens=101, expect_fresh=True)
        self.assertEqual(run["decode_tok_s"], 100.0)
        self.assertNotIn("client-engine-mismatch", run["flags"])

    def test_cached_tokens_counted_in_prompt_n_do_not_inflate_reading_speed(self):
        # Ollama's OpenAI endpoint: prompt_n includes cached tokens, prompt_ms covers fresh ones, no cache_n.
        usage = {"prompt_tokens": 16000, "completion_tokens": 101, "prompt_tokens_details": {"cached_tokens": 15000}}
        timings = {"prompt_n": 16000, "prompt_ms": 500.0, "predicted_n": 101, "predicted_ms": 1010.0}
        run = derive_run(stream(usage=usage, timings=timings), max_tokens=101, expect_fresh=False, expect_cache=True)
        self.assertAlmostEqual(run["engine_prefill_tok_s"], 2000.0)  # 1,000 fresh tokens in 0.5 s, not 32,000 tok/s

    def test_hidden_tokens_are_detected_and_not_counted_in_the_window(self):
        # 200 tokens generated at 100 tok/s, but the first 100 (thinking) are never streamed.
        # Visible stream: 100 one-token events over 0.99 s. Usage still says 200.
        hidden = stream(first_token_s=2.0, first_answer_s=2.0, last_token_s=2.99, wall_s=3.0, text_events=100, answer_events=100, answer_chars=450, first_event_chars=4,
                        usage={"prompt_tokens": 4000, "completion_tokens": 200})
        run = derive_run(hidden, max_tokens=200, expect_fresh=True)
        self.assertIn("hidden-tokens", run["flags"])
        self.assertEqual(run["hidden_tokens"], 100)
        self.assertAlmostEqual(run["decode_tok_s"], 100.0, places=6)   # naive usage/window would say 202
        self.assertNotIn("buffered-stream", run["flags"])

    def test_buffered_stream_is_not_mistaken_for_hidden_tokens(self):
        buffered = client_decode_rate(160, 10, 80, 800, 1.8)   # 80 characters per event
        self.assertEqual(buffered["hidden_tokens"], 0)

    def test_two_short_tokens_per_event_are_buffering_not_hidden_tokens(self):
        # 100 tokens of code-like text (3.1 characters each) sent two per event at a true
        # 100 tok/s. A fixed "8 characters is one token" rule read this as 50 hidden tokens
        # and reported half the real speed.
        pairs = stream(first_token_s=1.02, first_answer_s=1.02, last_token_s=2.0, wall_s=2.01, text_events=50, answer_events=50, answer_chars=310,
                       first_event_chars=6, usage={"prompt_tokens": 4000, "completion_tokens": 100})
        run = derive_run(pairs, max_tokens=100, expect_fresh=True, chars_per_token=3.1)
        self.assertEqual(run["hidden_tokens"], 0)
        self.assertAlmostEqual(run["decode_tok_s"], 100.0, delta=0.2)
        self.assertIn("buffered-stream", run["flags"])        # no engine figure to check it against
        self.assertNotIn("hidden-tokens", run["flags"])

    def test_declared_reasoning_tokens_that_were_not_streamed_are_hidden(self):
        # The server says 100 of 200 tokens were reasoning, and no reasoning was streamed.
        usage = {"prompt_tokens": 4000, "completion_tokens": 200, "completion_tokens_details": {"reasoning_tokens": 100}}
        hidden = stream(first_token_s=2.0, first_answer_s=2.0, last_token_s=2.99, wall_s=3.0, text_events=100, answer_events=100, answer_chars=900, first_event_chars=9, usage=usage)
        run = derive_run(hidden, max_tokens=200, expect_fresh=True)
        self.assertEqual((run["hidden_tokens"], run["hidden_tokens_source"]), (100, "usage"))
        self.assertAlmostEqual(run["decode_tok_s"], 100.0, places=6)
        self.assertIn("hidden-tokens", run["flags"])
        self.assertNotIn("buffered-stream", run["flags"])
        # 4,000 tokens: 2.0 s to the first event, of which 1.01 s went on writing 101 tokens
        self.assertAlmostEqual(run["client_prefill_tok_s"], 4000 / 0.99, delta=1.0)

    def test_streamed_reasoning_is_not_hidden(self):
        usage = {"prompt_tokens": 4000, "completion_tokens": 101, "completion_tokens_details": {"reasoning_tokens": 60}}
        run = derive_run(stream(usage=usage, reasoning_events=60, answer_events=41, reasoning_chars=300, answer_chars=205), max_tokens=101, expect_fresh=True)
        self.assertEqual(run["hidden_tokens"], 0)
        self.assertEqual(run["flags"], [])

    def test_the_engine_settles_whether_tokens_were_hidden(self):
        # Events of 9 characters look like two tokens each, so the stream alone says
        # "buffered" and 200 tok/s. The engine says 100: the other 100 tokens were hidden.
        shape = dict(first_token_s=2.0, first_answer_s=2.0, last_token_s=2.99, wall_s=3.0, text_events=100, answer_events=100, answer_chars=900, first_event_chars=9,
                     usage={"prompt_tokens": 4000, "completion_tokens": 200})
        alone = derive_run(stream(**shape), max_tokens=200, expect_fresh=True)
        self.assertAlmostEqual(alone["decode_tok_s"], 200.0, delta=1.0)
        self.assertIn("buffered-stream", alone["flags"])
        timings = {"prompt_n": 4000, "prompt_ms": 1000.0, "predicted_n": 200, "predicted_ms": 2000.0, "cache_n": 0}
        checked = derive_run(stream(timings=timings, **shape), max_tokens=200, expect_fresh=True)
        self.assertEqual((checked["hidden_tokens"], checked["hidden_tokens_source"]), (100, "engine"))
        self.assertAlmostEqual(checked["client_decode_tok_s"], 100.0, places=6)
        self.assertNotIn("client-engine-mismatch", checked["flags"])
        self.assertIn("hidden-tokens", checked["flags"])

    def test_the_engine_can_also_overrule_a_hidden_token_guess(self):
        # One-token-sized events, half as many as tokens: the stream alone says "hidden".
        # An engine rate that matches the buffered reading shows every token was streamed.
        shape = dict(first_token_s=1.02, first_answer_s=1.02, last_token_s=2.0, wall_s=2.01, text_events=50, answer_events=50, answer_chars=250, first_event_chars=5,
                     usage={"prompt_tokens": 4000, "completion_tokens": 100})
        alone = derive_run(stream(**shape), max_tokens=100, expect_fresh=True)
        self.assertEqual((alone["hidden_tokens"], alone["hidden_tokens_source"]), (50, "stream"))
        timings = {"prompt_n": 4000, "prompt_ms": 1000.0, "predicted_n": 100, "predicted_ms": 1000.0, "cache_n": 0}
        checked = derive_run(stream(timings=timings, **shape), max_tokens=100, expect_fresh=True)
        self.assertEqual(checked["hidden_tokens"], 0)
        self.assertAlmostEqual(checked["client_decode_tok_s"], 100.0, delta=0.2)
        self.assertEqual(checked["flags"], [])

    def test_neither_reading_matching_the_engine_is_a_mismatch(self):
        shape = dict(first_token_s=1.02, first_answer_s=1.02, last_token_s=2.0, wall_s=2.01, text_events=50, answer_events=50, answer_chars=250, first_event_chars=5,
                     usage={"prompt_tokens": 4000, "completion_tokens": 100})
        timings = {"prompt_n": 4000, "prompt_ms": 1000.0, "predicted_n": 100, "predicted_ms": 5000.0, "cache_n": 0}   # 20 tok/s
        run = derive_run(stream(timings=timings, **shape), max_tokens=100, expect_fresh=True)
        self.assertIn("client-engine-mismatch", run["flags"])
        self.assertAlmostEqual(run["decode_tok_s"], 20.0)

    def test_log_timings_keep_their_source_and_the_pause_between_passes(self):
        timings = {"source": "strata-engine-log", "passes": 2, "cache_n": 0, "prompt_n": 4494, "prompt_ms": 5202.0, "predicted_n": 83, "predicted_ms": 3090.0,
                   "between_pass_tokens": 17, "between_pass_ms": 304.0}
        engine = normalize_engine({"timings": timings})
        self.assertEqual((engine["source"], engine["passes"], engine["between_pass_tokens"], engine["between_pass_ms"]), ("strata-engine-log", 2, 17, 304.0))

    def test_client_engine_mismatch_is_flagged(self):
        timings = {"prompt_n": 4000, "prompt_ms": 400.0, "predicted_n": 101, "predicted_ms": 2020.0, "cache_n": 0}  # engine says 50 tok/s
        run = derive_run(stream(timings=timings), max_tokens=101, expect_fresh=True)  # client stream says 100 tok/s
        self.assertIn("client-engine-mismatch", run["flags"])
        self.assertEqual(run["decode_source"], "engine")
        self.assertAlmostEqual(run["decode_tok_s"], 50.0)


class FitAndConventionTest(unittest.TestCase):
    def test_fixed_cost_is_separated_from_the_marginal_rate(self):
        # 3 s per request plus 2,600 tok/s, with a little noise.
        fit = fit_reading([(4000, 4.6), (16000, 9.1), (64000, 27.9), (128000, 52.0)])
        self.assertIsNotNone(fit)
        self.assertAlmostEqual(fit["fixed_s"], 3.0, delta=0.3)
        self.assertAlmostEqual(fit["marginal_tok_s"], 2600, delta=120)
        self.assertGreater(fit["r_squared"], 0.99)
        # The v1 DeepSeek rows suggest the same shape (a line puts them near 2.7 s plus
        # 2,590 tok/s), but the 4.5K read is 12% off that line, so no rule is claimed.
        self.assertIsNone(fit_reading([(4494, 5.084), (15119 - 3982, 7.06), (50119, 21.3), (250119, 99.5)]))

    def test_no_fit_when_a_line_does_not_describe_the_points(self):
        self.assertIsNone(fit_reading([(4000, 0.4), (16000, 1.8)]))                       # two points prove nothing
        self.assertIsNone(fit_reading([(4000, 0.45), (16000, 1.75), (64000, 15.4)]))        # reading slows with depth: curved
        self.assertIsNone(fit_reading([(4000, 2.0), (16000, 2.0), (64000, 2.0)]))           # flat

    def test_no_fit_when_the_largest_prompt_alone_makes_the_line(self):
        # A line through all three points has R squared 0.99, but only because the 64K point
        # dominates it. The two smaller sizes predict 4.3 s for a read that took 9.6 s.
        points = [(4000, 0.9), (16000, 2.0), (64000, 9.6)]
        self.assertIsNone(fit_reading(points))
        # with the largest read in line with the smaller ones, the fit is reported with its miss
        fit = fit_reading([(4000, 0.9), (16000, 2.0), (64000, 6.5)])
        self.assertAlmostEqual(fit["marginal_tok_s"], 10700, delta=400)
        self.assertLess(abs(fit["holdout_error_pct"]), 5.0)
        self.assertEqual(fit["points"], 3)

    def test_engine_rate_follows_the_runtimes_own_convention_exactly(self):
        llama = normalize_engine({"timings": {"predicted_n": 101, "predicted_ms": 1000.0, "predicted_per_second": 100.0}})
        self.assertEqual((llama["decode_tok_s"], llama["decode_convention"]), (100.0, "first-token-excluded"))
        strata = normalize_engine({"timings": {"predicted_n": 83, "predicted_ms": 3090.0, "predicted_per_second": 26.9}})   # rounded to 0.1
        self.assertAlmostEqual(strata["decode_tok_s"], 26.8608, places=3)
        self.assertEqual(strata["decode_convention"], "all-tokens")
        log_derived = normalize_engine({"timings": {"predicted_n": 83, "predicted_ms": 3090.0}})
        self.assertEqual(log_derived["decode_convention"], "all-tokens")


if __name__ == "__main__":
    unittest.main()
