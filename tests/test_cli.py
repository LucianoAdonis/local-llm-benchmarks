"""Command-line input handling: every mistake ends in one readable line and exit status 2."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from llmbench.cli import main
from llmbench.mockserver import MockServer


def run_cli(argv, env=None):
    buffer = io.StringIO()
    with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(buffer):
        code = main(argv)
    return code, buffer.getvalue()


class InputErrorTest(unittest.TestCase):
    def test_a_bad_address_is_refused_before_anything_runs(self):
        code, text = run_cli(["doctor", "--url", "http://[bad"])
        self.assertEqual(code, 2)
        self.assertIn("--url not a usable address", text)

    def test_extra_body_must_be_an_object(self):
        code, text = run_cli(["run", "--url", "http://127.0.0.1:9", "--extra-body", "[1, 2]"])
        self.assertEqual(code, 2)
        self.assertIn("must be a JSON object", text)

    def test_an_api_key_with_a_line_break_is_refused_without_echoing_it(self):
        code, text = run_cli(["run", "--url", "http://127.0.0.1:9", "--api-key-env", "LLMBENCH_TEST_KEY"], {"LLMBENCH_TEST_KEY": "secret-value\nmore"})
        self.assertEqual(code, 2)
        self.assertNotIn("secret-value", text)

    def test_an_unset_key_variable_is_named(self):
        os.environ.pop("LLMBENCH_SURELY_UNSET", None)
        code, text = run_cli(["run", "--url", "http://127.0.0.1:9", "--api-key-env", "LLMBENCH_SURELY_UNSET"])
        self.assertEqual(code, 2)
        self.assertIn("LLMBENCH_SURELY_UNSET is not set", text)

    def test_broken_and_foreign_files_are_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as folder:
            broken, foreign = Path(folder, "broken.json"), Path(folder, "other.json")
            broken.write_text('{"a":', encoding="utf-8")
            foreign.write_text("[1, 2]", encoding="utf-8")
            for argv in (["report", str(broken)], ["report", str(foreign)], ["compare", str(foreign), str(foreign)], ["report", str(Path(folder, "missing.json"))]):
                code, text = run_cli(argv)
                self.assertEqual(code, 2, argv)
                self.assertTrue(text.startswith("Error: "), text)

    def test_wildcards_are_expanded_for_shells_that_do_not(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("a.json", "b.json"):
                Path(folder, name).write_text(json.dumps({"tok_s": 1.0}), encoding="utf-8")
            code, text = run_cli(["sanitize", "--check", os.path.join(folder, "*.json")])
            self.assertEqual(code, 0)
            self.assertIn("2 file(s)", text)
            code, text = run_cli(["sanitize", "--check", os.path.join(folder, "*.nothing")])
            self.assertEqual(code, 2)

    @mock.patch("llmbench.cli.subprocess.run")
    @mock.patch("llmbench.cli.shutil.which", return_value="/tools/lms")
    def test_pull_delegates_the_model_id_as_a_single_argument(self, which, run):
        run.return_value.returncode = 0
        code, text = run_cli(["pull", "--backend", "bionic", "--model", "llama-3.1-8b@q4_k_m; echo unsafe"])
        self.assertEqual(code, 0)
        self.assertIn("native model manager", text)
        run.assert_called_once_with(["/tools/lms", "get", "llama-3.1-8b@q4_k_m; echo unsafe"], check=False)

    @mock.patch("llmbench.cli.shutil.which", return_value=None)
    def test_pull_explains_when_lms_is_missing(self, which):
        code, text = run_cli(["pull", "--model", "some-model"])
        self.assertEqual(code, 2)
        self.assertIn("`lms` command was not found", text)


class SaveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = MockServer(port=0, prefill_tok_s=400000.0, decode_tok_s=3000.0, overhead_ms=0.0).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_the_saved_file_is_what_was_shown_and_the_checkpoint_is_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            output = os.path.join(folder, "result.json")
            code, text = run_cli(["run", "--url", self.server.url, "--suite", "quick", "--scenarios", "chat", "--runs", "1", "--output", output])
            self.assertIn(code, (0, 1))
            self.assertTrue(Path(output).exists())
            self.assertFalse(Path(output + ".partial.json").exists())
            self.assertIn("Saved: %s" % output, text)
            self.assertNotIn(self.server.url, Path(output).read_text(encoding="utf-8"))

    def test_an_unwritable_place_fails_before_the_run(self):
        with tempfile.TemporaryDirectory() as folder:
            blocker = Path(folder, "file")
            blocker.write_text("", encoding="utf-8")
            code, text = run_cli(["run", "--url", self.server.url, "--suite", "quick", "--output", str(blocker / "sub" / "r.json")])
            self.assertEqual(code, 2)
            self.assertIn("cannot save results", text)


if __name__ == "__main__":
    unittest.main()
