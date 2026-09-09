import json
import unittest

import local_ai_service
from local_ai_service import LocalAIManager


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({"response": self.body}).encode("utf-8")


class FakeProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class LocalAIServiceTests(unittest.TestCase):
    def test_starts_ollama_sends_keep_alive_and_shuts_down_when_idle(self):
        now = [1000]
        processes = []
        requests = []

        def fake_popen(*args, **kwargs):
            process = FakeProcess()
            processes.append(process)
            return process

        def fake_opener(request, timeout=None):
            requests.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse("trail clear")

        original_which = local_ai_service.shutil.which
        original_run = local_ai_service.subprocess.run
        original_timer = local_ai_service.threading.Timer
        try:
            local_ai_service.shutil.which = lambda name: "/usr/bin/ollama"
            local_ai_service.subprocess.run = lambda *args, **kwargs: None
            local_ai_service.threading.Timer = lambda *args, **kwargs: type(
                "FakeTimer",
                (),
                {"daemon": False, "start": lambda self: None, "cancel": lambda self: None},
            )()
            manager = LocalAIManager(
                {
                    "enabled": True,
                    "model": "tinyllama",
                    "idle_shutdown_seconds": 1200,
                    "url": "http://127.0.0.1:11434/api/generate",
                },
                clock=lambda: now[0],
                popen=fake_popen,
                opener=fake_opener,
            )

            ok, response = manager.ask("where next?")
            self.assertTrue(ok)
            self.assertEqual("trail clear", response)
            self.assertEqual("tinyllama", requests[0]["model"])
            self.assertEqual("20m", requests[0]["keep_alive"])
            self.assertFalse(manager.shutdown_if_idle(now=2199))
            self.assertFalse(processes[0].terminated)
            self.assertTrue(manager.shutdown_if_idle(now=2200))
            self.assertTrue(processes[0].terminated)
        finally:
            local_ai_service.shutil.which = original_which
            local_ai_service.subprocess.run = original_run
            local_ai_service.threading.Timer = original_timer

    def test_reports_unsupported_32_bit_arm_without_ollama(self):
        original_which = local_ai_service.shutil.which
        original_machine = local_ai_service.platform.machine
        original_architecture = local_ai_service.platform.architecture
        try:
            local_ai_service.shutil.which = lambda name: None
            local_ai_service.platform.machine = lambda: "armv7l"
            local_ai_service.platform.architecture = lambda: ("32bit", "")
            manager = LocalAIManager({"enabled": True})

            ok, message = manager.ensure_started()

            self.assertFalse(ok)
            self.assertIn("32-bit ARM", message)
        finally:
            local_ai_service.shutil.which = original_which
            local_ai_service.platform.machine = original_machine
            local_ai_service.platform.architecture = original_architecture


if __name__ == "__main__":
    unittest.main()
