import os
import tempfile
import unittest

from llmbench.workload import (
    Corpus,
    Rng,
    chat_messages,
    compress_ratio,
    context_messages,
    followup_messages,
    load_file_corpus,
    message_chars,
    seed_from,
)

GOLDEN_SEED = seed_from("llmbench", "golden", 0)


class RngTest(unittest.TestCase):
    def test_known_sequence(self):
        # SplitMix64 reference values. If these change, every published workload changes.
        rng = Rng(42)
        self.assertEqual([rng.next() for _ in range(3)], [13679457532755275413, 2949826092126892291, 5139283748462763858])

    def test_seed_from_is_stable(self):
        self.assertEqual(GOLDEN_SEED, 6740444650579952180)

    def test_sample_is_distinct(self):
        picked = Rng(7).sample(list(range(20)), 8)
        self.assertEqual(len(set(picked)), 8)


class CorpusTest(unittest.TestCase):
    def test_golden_hashes(self):
        """Workload text is pinned. Changing it requires bumping WORKLOAD_VERSION."""
        _, diverse = Corpus("diverse").build(64000, GOLDEN_SEED)
        self.assertEqual(diverse["sha256"], "dec28b1e7eba60f097f26fb82c57bfa34d3b0f5caabc4b45b1e9b4a907ecc39c")
        _, repetitive = Corpus("repetitive").build(64000, GOLDEN_SEED)
        self.assertEqual(repetitive["sha256"], "da4fcf2a73392666795042d0a28e963b8ed1609779388e66ba0ad6c4ac84b5c5")

    def test_size_is_close_to_target(self):
        for target in (500, 5000, 50000):
            text, info = Corpus("diverse").build(target, 123)
            self.assertLessEqual(len(text), target)
            self.assertGreater(len(text), target - 400)
            self.assertEqual(info["chars"], len(text))

    def test_different_seeds_share_no_long_prefix(self):
        a, _ = Corpus("diverse").build(8000, seed_from("x", 1))
        b, _ = Corpus("diverse").build(8000, seed_from("x", 2))
        common = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        self.assertLess(common, 40)

    def test_diverse_is_as_compressible_as_real_code_and_repetitive_is_not(self):
        diverse, _ = Corpus("diverse").build(200000, 5)
        repetitive, _ = Corpus("repetitive").build(200000, 5)
        self.assertTrue(3.0 <= compress_ratio(diverse) <= 6.5, compress_ratio(diverse))
        self.assertGreater(compress_ratio(repetitive), 20.0)

    def test_file_corpus_hides_absolute_paths_and_reports_wrap(self):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, "pkg", ".git"))
            with open(os.path.join(folder, "pkg", "a.py"), "w", encoding="utf-8") as handle:
                handle.write("def alpha():\n    return 1\n" * 20)
            with open(os.path.join(folder, "pkg", "b.md"), "w", encoding="utf-8") as handle:
                handle.write("# Title\n\nSome prose.\n" * 20)
            with open(os.path.join(folder, "pkg", ".git", "config.txt"), "w", encoding="utf-8") as handle:
                handle.write("secret")
            with open(os.path.join(folder, "pkg", "blob.bin"), "wb") as handle:
                handle.write(b"\x00\xff" * 10)
            files = load_file_corpus(folder)
            self.assertEqual([rel for rel, _ in files], ["pkg/a.py", "pkg/b.md"])
            corpus = Corpus("file:" + folder)
            text, info = corpus.build(5000, 9)
            self.assertNotIn(folder, text)
            self.assertTrue(info["wrapped"])
            self.assertEqual(info["kind"], "file")
            self.assertIn("source_sha256", info)

    def test_unknown_corpus_is_rejected(self):
        with self.assertRaises(ValueError):
            Corpus("mystery")


class PromptTest(unittest.TestCase):
    def test_nonce_comes_before_the_corpus(self):
        messages = context_messages("BODY", "abc-1")
        user = messages[1]["content"]
        self.assertLess(user.index("abc-1"), user.index("BODY"))
        self.assertEqual(messages[0]["role"], "system")

    def test_followup_extends_the_first_turn_unchanged(self):
        first = context_messages("BODY", "n1")
        second = followup_messages(first, "the answer", "n2", 3)
        self.assertEqual(second[: len(first)], first)
        self.assertEqual(second[-2], {"role": "assistant", "content": "the answer"})
        self.assertIn("n2", second[-1]["content"])

    def test_followup_survives_an_empty_answer(self):
        second = followup_messages(context_messages("BODY", "n1"), "", "n2", 3)
        self.assertTrue(second[-2]["content"])

    def test_chat_prompt_is_deterministic_per_seed(self):
        self.assertEqual(chat_messages("n", 11), chat_messages("n", 11))
        self.assertGreater(message_chars(chat_messages("n", 11)), 100)


if __name__ == "__main__":
    unittest.main()
