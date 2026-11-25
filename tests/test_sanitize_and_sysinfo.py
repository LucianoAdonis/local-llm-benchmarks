import json
import os
import tempfile
import unittest
from pathlib import Path

from llmbench import sysinfo
from llmbench.sanitize import clean, identity_terms, residue, sanitize_file


NO_IDENTITY = []  # keep the pattern tests independent of the machine they run on


def scrub(text):
    return clean(text, NO_IDENTITY)


class SanitizeTest(unittest.TestCase):
    def test_home_paths_on_every_os(self):
        self.assertEqual(scrub("C:\\Users\\someone\\AppData\\Local\\Strata\\x.log"), "<USER_HOME>\\AppData\\Local\\Strata\\x.log")
        self.assertEqual(scrub("C:/Users/someone/models/a.gguf"), "<USER_HOME>/models/a.gguf")
        self.assertEqual(scrub("d:\\\\Users\\\\someone\\\\x"), "<USER_HOME>\\\\x")              # doubled backslashes, other drive
        self.assertEqual(scrub("file:///C:/Users/someone/x.json"), "file:///<USER_HOME>/x.json")
        self.assertEqual(scrub("/Users/someone/models/a.gguf"), "<USER_HOME>/models/a.gguf")
        self.assertEqual(scrub("log at /home/someone/.cache/x"), "log at <USER_HOME>/.cache/x")
        self.assertEqual(scrub("/mnt/c/Users/someone/x"), "<USER_HOME>/x")                                  # WSL
        self.assertEqual(scrub("\\\\fileserver\\share\\model.gguf"), "\\\\<HOST>\\share\\model.gguf")  # UNC host
        self.assertEqual(scrub("see docs/Users/guide.md"), "see docs/Users/guide.md")

    def test_a_path_does_not_swallow_the_rest_of_the_line(self):
        # v1's pattern ran to the next slash or quote and destroyed the numbers after it.
        text = "log C:\\Users\\someone and 3 other files, decode 27.2 tok/s"
        self.assertEqual(scrub(text), "log <USER_HOME> and 3 other files, decode 27.2 tok/s")

    def test_addresses(self):
        self.assertEqual(scrub("http://127.0.0.1:8080/v1/chat/completions"), "<LOCAL_API_URL>/v1/chat/completions")
        self.assertEqual(scrub("http://localhost:1234/v1"), "<LOCAL_API_URL>/v1")
        self.assertEqual(scrub("http://[::1]:8080/v1"), "<LOCAL_API_URL>/v1")
        self.assertEqual(scrub("http://localhost.example.com/v1"), "<REMOTE_URL>/v1")                      # not loopback, and not a known public site
        self.assertEqual(scrub("http://192.168.1.50:11434/api"), "<LAN_API_URL>/api")
        self.assertEqual(scrub("http://10.0.0.7:1234"), "<LAN_API_URL>")
        self.assertEqual(scrub("http://100.101.102.103:8080/v1"), "<LAN_API_URL>/v1")                      # carrier-grade / VPN range
        self.assertEqual(scrub("http://gpu-box.local:8080/v1"), "<LAN_API_URL>/v1")
        self.assertEqual(scrub("connected to 192.168.1.50 on port 1234"), "connected to <LAN_IP> on port 1234")
        self.assertEqual(scrub("host gpu-box.local answered"), "host <HOST> answered")
        self.assertEqual(scrub("https://huggingface.co/unsloth/model"), "https://huggingface.co/unsloth/model")
        self.assertEqual(scrub("Windows 10.0.26100 and llama.cpp 1.0.0"), "Windows 10.0.26100 and llama.cpp 1.0.0")

    def test_secrets(self):
        self.assertEqual(scrub("key sk-Abc123def456GHI789jkl end"), "key <REDACTED_SECRET> end")
        self.assertEqual(scrub("task-sk-learn-pipeline-benchmark-run-0001"), "task-sk-learn-pipeline-benchmark-run-0001")  # a word, not a key
        for secret in ("hf_abcdefghijklmnopqrstuvwx", "github_pat_11ABCDEFG0abcdefghij_klmnop", "ghp_abcdefghijklmnopqrstuv", "AKIAABCDEFGHIJKLMNOP",
                       "AIzaSyA1234567890abcdefghijklmnopqrstuv", "nvapi-abcdefghij1234567890ABCD", "xoxb-1234567890-abcdefghij",
                       "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop"):
            self.assertEqual(scrub("x %s y" % secret), "x <REDACTED_SECRET> y", secret)
        self.assertEqual(scrub("Authorization: Bearer abcdef1234567890XYZ"), "Authorization: Bearer <REDACTED_SECRET>")
        self.assertEqual(scrub("https://alice:hunter2@example.com/v1"), "https://<REDACTED>@example.com/v1")
        self.assertEqual(scrub("https://example.com/v1?api_key=abc123&model=x"), "<REMOTE_URL>/v1?api_key=<REDACTED>&model=x")
        cleaned = scrub({"api_key": "anything", "Authorization": "x", "token": "", "password": "p", "x-api-key": "k", "client_secret": "s", "Cookie": "c"})
        self.assertEqual(cleaned, {"api_key": "<REDACTED>", "Authorization": "<REDACTED>", "token": "", "password": "<REDACTED>", "x-api-key": "<REDACTED>", "client_secret": "<REDACTED>", "Cookie": "<REDACTED>"})

    def test_personal_identifiers(self):
        self.assertEqual(scrub("USERNAME=someone and USER=someone"), "USERNAME=<USER> and USER=<USER>")
        self.assertEqual(scrub("mail someone@example.com now"), "mail <EMAIL> now")
        self.assertEqual(scrub("pip install pkg@1.2.3"), "pip install pkg@1.2.3")                           # a version, not an address
        self.assertEqual(scrub("eth0 3C:22:FB:AA:BB:CC up"), "eth0 <MAC> up")
        self.assertEqual(scrub("GPU-1a2b3c4d-1234-5678-9abc-def012345678"), "<GPU_UUID>")
        self.assertEqual(scrub("2026-11-23T14:06:23 run"), "2026-11-23T14:06:23 run")                       # a time, not a MAC

    def test_identifying_keys_are_dropped_keys_are_cleaned_and_structure_kept(self):
        data = {"hostname": "my-pc", "username": "me", "serial_number": "C02X", "runs": [{"prompt_tokens": 5, "note": "/Users/me/x"}],
                "file:/Users/me/corpus": {"n": 1.5}, "ok": True, "none": None}
        self.assertEqual(scrub(data), {"runs": [{"prompt_tokens": 5, "note": "<USER_HOME>/x"}], "file:<USER_HOME>/corpus": {"n": 1.5}, "ok": True, "none": None})

    def test_this_machines_own_identity_is_removed_wherever_it_appears(self):
        home = os.path.expanduser("~")
        cleaned = clean({"note": "models live in %s/models" % home, "list": [home]})
        self.assertNotIn(home, json.dumps(cleaned))
        self.assertTrue(identity_terms().home_patterns)

    def test_a_short_login_name_is_removed_from_paths_only(self):
        from llmbench.sanitize import Identity
        who = Identity(home="/home/al", user="al")
        self.assertEqual(clean({"note": "/srv/al/models and al dente"}, who), {"note": "/srv/<USER>/models and al dente"})

    def test_residue_check(self):
        self.assertFalse(residue({"endpoint": "loopback:8080", "tok_s": 27.2}))
        self.assertTrue(residue({"endpoint": "http://127.0.0.1:8080"}))

    def test_file_round_trip_accepts_a_bom(self):
        with tempfile.TemporaryDirectory() as folder:
            source, destination = Path(folder, "in.json"), Path(folder, "out", "public.json")
            source.write_text("\ufeff" + json.dumps({"endpoint": "http://127.0.0.1:8080/v1"}), encoding="utf-8")
            sanitize_file(source, destination)
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), {"endpoint": "<LOCAL_API_URL>/v1"})

    def test_published_v1_results_stay_clean(self):
        folder = Path(__file__).resolve().parent.parent / "results" / "2026-11-23" / "coding-context"
        for path in sorted(folder.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(scrub(data), data, path.name)


class SysinfoTest(unittest.TestCase):
    def test_capture_never_raises_and_leaks_nothing_identifying(self):
        system = sysinfo.capture_system()
        state = sysinfo.capture_state()
        self.assertIn("platform", system)
        text = json.dumps({"system": system, "state": state})
        self.assertNotIn(os.path.expanduser("~"), text)
        for name in (os.environ.get("USER"), os.environ.get("USERNAME")):
            if name and len(name) > 3:
                self.assertNotIn(name, text)
        self.assertIsInstance(sysinfo.describe(system), str)
        self.assertIsInstance(sysinfo.preflight_warnings(system, state), list)

    def test_preflight_warnings(self):
        warnings = sysinfo.preflight_warnings({}, {
            "power_source": "battery", "low_power_mode": True, "power_plan": "Power saver", "cpu_speed_limit_pct": 70,
            "swap_used_mb": 4096, "memory_pressure": "critical",
            "gpu": {"temperature_c": 85, "vram_used_mb": 31900, "vram_total_mb": 32607},
        })
        self.assertEqual(len(warnings), 8)
        self.assertEqual(sysinfo.preflight_warnings({}, {"power_source": "ac", "swap_used_mb": 0, "memory_pressure": "normal"}), [])

    def test_describe(self):
        line = sysinfo.describe({"os": "Windows 11 Pro (build 26100)", "cpu": "AMD Ryzen 9 9950X3D", "gpus": [{"name": "NVIDIA GeForce RTX 5090", "vram_gb": 31.8}], "ram_gb": 127.6})
        self.assertEqual(line, "Windows 11 Pro (build 26100) | AMD Ryzen 9 9950X3D | NVIDIA GeForce RTX 5090 32 GB | 128 GB RAM")

    def test_gpu_sampler_is_a_no_op_without_nvidia_smi(self):
        sampler = sysinfo.GpuSampler()
        sampler.available = False
        sampler.start()
        self.assertIsNone(sampler.stop())


if __name__ == "__main__":
    unittest.main()
