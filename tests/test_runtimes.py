import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from llmbench.mockserver import MockServer
from llmbench.runtimes import (
    chat_models,
    choose_model,
    detect,
    endpoint_class,
    engine_log_mark,
    engine_log_timings,
    enrich_model,
    model_choice_problem,
    parse_engine_rows,
    public_model_id,
)

# Real rows from results/2026-11-23 (Strata engine 0.1.59, DeepSeek, 4.5K prompt).
ROW_1 = "maya ds4 serve: prompt 4494 tokens = 0 reused + 4494 read in 5202 ms (863.8 tok/s), 50 generated in 1875 ms (26.66 tok/s); CPU lane 1.1% of the experts"
ROW_2 = "maya ds4 serve: prompt 4561 tokens = 4544 reused + 17 read in 304 ms (55.9 tok/s), 33 generated in 1215 ms (27.17 tok/s); CPU lane 1.2% of the experts"
NOISE = "ds4 slots: saved a 4280-token conversation (0.02 GB in RAM in 0.0 s); 4 in RAM, 2 in <USER_HOME>\\AppData\\Local\\Strata\\install\\ds4-slots"


class FakeRuntime:
    """Serves canned JSON for GET routes so detection can be tested without the real apps."""

    def __init__(self, routes):
        routes = dict(routes)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _send(self, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200 if payload is not None else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                self._send(routes.get(self.path))

            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self._send(routes.get("POST " + self.path))

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.root = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class PublicModelIdTest(unittest.TestCase):
    def test_file_paths_are_cut_to_the_file_name(self):
        self.assertEqual(public_model_id("/Users/someone/models/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf"), "Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf")
        self.assertEqual(public_model_id("C:\\Users\\someone\\models\\model.gguf"), "model.gguf")
        self.assertEqual(public_model_id("models/sub/model.gguf"), "model.gguf")
        self.assertEqual(public_model_id("~/models/pack.strata"), "pack.strata")

    def test_names_that_merely_contain_a_slash_are_kept(self):
        for name in ("unsloth/Qwen3.6-35B-A3B-GGUF", "qwen/qwen3.5-9b", "hf.co/unsloth/Inkling-2-Mini-GGUF:UD-Q4_K_M", "gemma4:12b", "mock-model"):
            self.assertEqual(public_model_id(name), name)


class EndpointClassTest(unittest.TestCase):
    def test_classes_never_contain_the_address(self):
        self.assertEqual(endpoint_class("http://127.0.0.1:8080"), "loopback:8080")
        self.assertEqual(endpoint_class("http://localhost:1234"), "loopback:1234")
        self.assertEqual(endpoint_class("http://192.168.1.50:11434"), "lan:11434")
        self.assertEqual(endpoint_class("http://gpu-box.local:8080"), "lan:8080")
        self.assertEqual(endpoint_class("https://api.example.com"), "remote")


class DetectTest(unittest.TestCase):
    def test_generic_server(self):
        with MockServer() as server:
            info = detect(server.url)
        self.assertTrue(info["reachable"])
        self.assertEqual((info["name"], info["models"]), ("openai-compatible", ["mock-model"]))
        self.assertEqual(choose_model(info), "mock-model")

    def test_unreachable(self):
        self.assertFalse(detect("http://127.0.0.1:9", timeout=1)["reachable"])

    def test_lmstudio(self):
        routes = {
            "/v1/models": {"data": [{"id": "qwen-x"}, {"id": "text-embedding-nomic-embed-text-v1.5"}]},
            "/api/v0/models": {"data": [
                {"id": "qwen-x", "type": "llm", "arch": "qwen3", "compatibility_type": "mlx", "quantization": "4bit", "state": "loaded", "max_context_length": 262144, "loaded_context_length": 32768},
                {"id": "other-model", "type": "llm", "compatibility_type": "gguf", "quantization": "Q4_K_M", "state": "not-loaded", "max_context_length": 8192},
                {"id": "text-embedding-nomic-embed-text-v1.5", "type": "embeddings", "state": "not-loaded"},
            ]},
        }
        with FakeRuntime(routes) as fake:
            info = detect(fake.root)
            self.assertEqual(info["name"], "lmstudio")
            self.assertEqual(info["models"], ["qwen-x", "other-model"])
            self.assertEqual(choose_model(info), "qwen-x")
            enrich_model(fake.root, info, "qwen-x")
        self.assertEqual(info["context_tokens"], 32768)
        self.assertEqual(info["engine"], "mlx")
        self.assertEqual(info["model_details"]["quantization"], "4bit")
        self.assertNotIn("lmstudio_models", info)

    def test_ollama(self):
        routes = {
            "/v1/models": {"data": [{"id": "gemma:latest"}]},
            "/api/version": {"version": "0.40.2"},
            "/api/ps": {"models": [{"name": "gemma:latest", "size": 1000, "size_vram": 750, "context_length": 8192, "details": {"quantization_level": "Q4_K_M", "parameter_size": "8B"}}]},
        }
        with FakeRuntime(routes) as fake:
            info = detect(fake.root)
            self.assertEqual((info["name"], info["version"], info["loaded_models"]), ("ollama", "0.40.2", ["gemma:latest"]))
            enrich_model(fake.root, info, "gemma:latest")
        self.assertEqual(info["context_tokens"], 8192)
        self.assertEqual(info["model_details"]["gpu_fraction"], 0.75)
        self.assertEqual(info["model_details"]["quantization_level"], "Q4_K_M")

    def test_llama_cpp_keeps_only_the_file_name(self):
        routes = {
            "/v1/models": {"data": [{"id": "model.gguf", "meta": {"n_params": 8030261248, "n_ctx_train": 131072, "size": 4920000000}}]},
            "/props": {"default_generation_settings": {"n_ctx": 16384}, "total_slots": 1, "model_path": "C:\\Users\\someone\\models\\model-Q4_K_M.gguf", "build_info": "b6123-abc"},
        }
        with FakeRuntime(routes) as fake:
            info = detect(fake.root)
            enrich_model(fake.root, info, "model.gguf")
        self.assertEqual((info["name"], info["version"], info["context_tokens"]), ("llama.cpp", "b6123-abc", 16384))
        self.assertEqual(info["model_file"], "model-Q4_K_M.gguf")
        self.assertNotIn("someone", json.dumps(info))
        self.assertEqual(info["model_details"]["n_ctx_train"], 131072)

    def test_strata_is_told_apart_from_llama_cpp(self):
        routes = {
            "/v1/models": {"data": [{"id": "inkling-2-mini-sq-15", "context_length": 32768}]},
            "/props": {"n_ctx": 32768, "model_path": "/Users/someone/Strata/Inkling-2-Mini-SQ-15.strata", "build_info": "Strata 0.2.20"},
            "/health": {"status": "ok", "max_context": 32768, "model": "inkling-2-mini-sq-15", "family": "inkling2", "loaded": True, "service": "strata"},
        }
        with FakeRuntime(routes) as fake:
            info = detect(fake.root)
        self.assertEqual((info["name"], info["version"], info["context_tokens"]), ("strata", "Strata 0.2.20", 32768))
        self.assertEqual(info["model_file"], "Inkling-2-Mini-SQ-15.strata")
        self.assertEqual(info["server_props"]["health.family"], "inkling2")
        self.assertNotIn("someone", json.dumps(info))

    def test_lmstudio_v1_listing_gives_the_loaded_context(self):
        routes = {
            "/v1/models": {"data": [{"id": "qwen-x"}]},
            "/api/v0/models": {"data": [{"id": "qwen-x", "type": "llm", "compatibility_type": "gguf", "quantization": "Q4_K_M", "state": "loaded", "max_context_length": 262144}]},
            "/api/v1/models": {"models": [{"key": "qwen-x", "format": "gguf", "params_string": "9B", "quantization": {"name": "Q4_K_M", "bits_per_weight": 4.8},
                                           "loaded_instances": [{"id": "qwen-x", "config": {"context_length": 65536, "parallel": 4, "flash_attention": True}}]}]},
            "POST /api/v0/chat/completions": {"choices": [], "runtime": {"name": "llama.cpp-mac-arm64-apple-metal-advsimd", "version": "2.79.0"}, "model_info": {"arch": "qwen3", "quant": "Q4_K_M", "format": "gguf", "context_length": 65536}},
        }
        with FakeRuntime(routes) as fake:
            info = detect(fake.root)
            enrich_model(fake.root, info, "qwen-x")
        self.assertEqual(info["context_tokens"], 65536)
        self.assertEqual((info["engine"], info["engine_version"]), ("llama.cpp-mac-arm64-apple-metal-advsimd", "2.79.0"))
        self.assertEqual(info["model_details"]["loaded_parallel"], 4)
        self.assertEqual(info["model_details"]["bits_per_weight"], 4.8)

    def test_ambiguous_model_choice(self):
        self.assertIsNone(choose_model({"models": ["a", "b"], "loaded_models": []}))
        self.assertEqual(choose_model({"models": ["a", "b"], "loaded_models": ["b"]}), "b")
        self.assertEqual(choose_model({"models": ["a", "nomic-embed-text"], "loaded_models": []}), "a")
        # a loaded embedding model is never the benchmark target
        self.assertEqual(choose_model({"models": ["a", "nomic-embed-text"], "loaded_models": ["nomic-embed-text"]}), "a")
        self.assertIsNone(choose_model({"models": ["nomic-embed-text"], "loaded_models": ["nomic-embed-text"]}))
        self.assertEqual(chat_models({"models": ["a", "bge-m3", "b"]}), ["a", "b"])

    def test_the_reason_no_model_was_chosen_says_what_to_do(self):
        nothing = model_choice_problem({"name": "lmstudio", "models": [], "loaded_models": []})
        self.assertIn("no chat model", nothing)
        self.assertIn("lms get", nothing)
        self.assertNotIn("more than one", nothing)
        only_embeddings = model_choice_problem({"name": "ollama", "models": ["nomic-embed-text"], "loaded_models": []})
        self.assertIn("only embedding models", only_embeddings)
        self.assertIn("ollama pull", only_embeddings)
        several = model_choice_problem({"name": "llama.cpp", "models": ["/home/someone/a.gguf", "b"], "loaded_models": []})
        self.assertIn("more than one model is available", several)
        self.assertIn("a.gguf, b", several)
        self.assertNotIn("someone", several)
        loaded = model_choice_problem({"name": "lmstudio", "models": ["a", "b", "c"], "loaded_models": ["a", "b"]})
        self.assertIn("more than one model is loaded", loaded)
        self.assertNotIn("c", loaded.split("one of:")[1])


class DoctorTest(unittest.TestCase):
    def run_doctor(self, routes):
        import contextlib, io
        from llmbench.cli import main
        with FakeRuntime(routes) as fake:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = main(["doctor", "--url", fake.root])
        return code, buffer.getvalue()

    def test_a_runtime_without_a_chat_model_is_not_ready(self):
        routes = {
            "/v1/models": {"data": [{"id": "text-embedding-nomic-embed-text-v1.5"}]},
            "/api/v0/models": {"data": [{"id": "text-embedding-nomic-embed-text-v1.5", "type": "embeddings", "state": "not-loaded"}]},
        }
        code, text = self.run_doctor(routes)
        self.assertEqual(code, 1)
        self.assertIn("Not ready: LM Studio", text)
        self.assertIn("no chat model", text)
        self.assertNotIn("Next:", text)

    def test_a_runtime_with_a_model_gets_the_next_step(self):
        code, text = self.run_doctor({"/v1/models": {"data": [{"id": "some-model"}]}})
        self.assertEqual(code, 0)
        self.assertRegex(text, r"Next: (py|python3) -m llmbench run --suite quick")


class EngineLogTest(unittest.TestCase):
    def test_rows_parse(self):
        rows = parse_engine_rows("\n".join([NOISE, ROW_1, ROW_2]))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {"prompt": 4494, "reused": 0, "read": 4494, "prefill_ms": 5202, "generated": 50, "decode_ms": 1875})
        self.assertEqual(rows[1]["reused"], 4544)

    def write_log(self, folder, before, after):
        path = os.path.join(folder, "engine.log")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(before)
        mark = engine_log_mark(path)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(after)
        return path, mark

    def test_first_pass_prefill_and_all_pass_decode(self):
        with tempfile.TemporaryDirectory() as folder:
            path, mark = self.write_log(folder, "old line\n" + ROW_1.replace("4494", "9999") + "\n", NOISE + "\n" + ROW_1 + "\n" + ROW_2 + "\n")
            timings = engine_log_timings(path, mark, 4494, wait_s=2.0)
        self.assertEqual(timings["passes"], 2)
        self.assertEqual((timings["prompt_n"], timings["prompt_ms"], timings["cache_n"]), (4494, 5202.0, 0))
        self.assertEqual((timings["predicted_n"], timings["predicted_ms"]), (83, 3090.0))
        self.assertEqual((timings["between_pass_tokens"], timings["between_pass_ms"]), (17, 304.0))
        first_pass = timings["prompt_n"] * 1000 / timings["prompt_ms"]
        v1_all_passes = timings["all_passes_read"] * 1000 / timings["all_passes_prefill_ms"]
        self.assertAlmostEqual(first_pass, 863.9, places=1)
        self.assertAlmostEqual(v1_all_passes, 819.3, places=1)  # what v1 published for this run

    def test_foreign_rows_are_skipped_and_never_summed(self):
        foreign = "maya ds4 serve: prompt 212 tokens = 0 reused + 212 read in 290 ms (731.0 tok/s), 12 generated in 400 ms (30.00 tok/s)"
        with tempfile.TemporaryDirectory() as folder:
            # a title-generation request from another client lands first, then ours, then another stray
            path, mark = self.write_log(folder, "", "\n".join([foreign, ROW_1, ROW_2, foreign]) + "\n")
            timings = engine_log_timings(path, mark, 4494, completion_tokens=100, wait_s=2.0)
        self.assertEqual(timings["passes"], 2)
        self.assertEqual((timings["prompt_n"], timings["predicted_n"], timings["between_pass_tokens"]), (4494, 83, 17))

    def test_waits_for_rows_that_account_for_the_billed_tokens(self):
        import threading, time as _time
        with tempfile.TemporaryDirectory() as folder:
            path, mark = self.write_log(folder, "", ROW_1 + "\n")
            def late():
                _time.sleep(0.9)   # v1 gave up 0.3 s after the first row and would have missed this
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write(ROW_2 + "\n")
            threading.Thread(target=late, daemon=True).start()
            timings = engine_log_timings(path, mark, 4494, completion_tokens=100, wait_s=4.0)
        self.assertEqual(timings["passes"], 2)

    def test_rows_from_another_request_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path, mark = self.write_log(folder, "", ROW_1 + "\n")
            self.assertIsNone(engine_log_timings(path, mark, 27619, wait_s=1.5))

    def test_missing_log_or_rows(self):
        self.assertIsNone(engine_log_mark("/no/such/file.log"))
        self.assertIsNone(engine_log_timings(None, None, 100))
        with tempfile.TemporaryDirectory() as folder:
            path, mark = self.write_log(folder, "nothing useful\n", "still nothing\n")
            self.assertIsNone(engine_log_timings(path, mark, 100, wait_s=0.6))


if __name__ == "__main__":
    unittest.main()
