import json
import logging
import platform
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request


DEFAULT_LOCAL_AI = {
    "enabled": True,
    "url": "http://127.0.0.1:11434/api/generate",
    "model": "tinyllama",
    "timeout_seconds": 120,
    "idle_shutdown_seconds": 1200,
    "startup_timeout_seconds": 120,
    "install_hint": "Install Ollama and pull the tinyllama model, or point Local AI URL at another Ollama server.",
}


class LocalAIManager:
    def __init__(self, config=None, clock=None, popen=subprocess.Popen, opener=urllib.request.urlopen):
        self.config = {**DEFAULT_LOCAL_AI, **(config or {})}
        self.clock = clock or time.time
        self.popen = popen
        self.opener = opener
        self.process = None
        self.last_used_at = None
        self.idle_timer = None
        self.lock = threading.Lock()
        self.logger = logging.getLogger(__name__)

    def update_config(self, config):
        self.config = {**DEFAULT_LOCAL_AI, **(config or {})}

    def enabled(self):
        return bool(self.config.get("enabled", True))

    def available(self):
        return shutil.which("ollama") is not None

    def availability_message(self):
        if self.available():
            return None
        machine = platform.machine().lower()
        if machine in ("armv6l", "armv7l") or (machine.startswith("arm") and platform.architecture()[0] == "32bit"):
            return (
                "Local AI needs Ollama, but Ollama does not support this 32-bit ARM OS. "
                "Use 64-bit Pi OS or set Local AI URL to another Ollama server."
            )
        return self.config.get("install_hint") or DEFAULT_LOCAL_AI["install_hint"]

    def model(self):
        return self.config.get("model") or DEFAULT_LOCAL_AI["model"]

    def idle_shutdown_seconds(self):
        return int(self.config.get("idle_shutdown_seconds", DEFAULT_LOCAL_AI["idle_shutdown_seconds"]))

    def touch(self):
        self.last_used_at = int(self.clock())
        self._schedule_idle_shutdown()

    def _schedule_idle_shutdown(self):
        if self.idle_timer:
            self.idle_timer.cancel()
        delay = self.idle_shutdown_seconds()
        self.idle_timer = threading.Timer(delay, self.shutdown_if_idle)
        self.idle_timer.daemon = True
        self.idle_timer.start()

    def ensure_started(self):
        if not self.enabled():
            return False, "Local AI is disabled in Config."
        if not self.available():
            return False, self.availability_message()
        with self.lock:
            self.touch()
            if self.process and self.process.poll() is None:
                return True, "Local AI is running."
            try:
                self.process = self.popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                self.logger.warning("Failed to start Ollama: %s", exc)
                return False, "Local AI could not start."
        return True, "Local AI is starting."

    def wait_until_ready(self, timeout=None, stop_event=None):
        timeout = timeout or int(self.config.get("startup_timeout_seconds", DEFAULT_LOCAL_AI["startup_timeout_seconds"]))
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            if stop_event and stop_event.is_set():
                return False, "Local AI startup was canceled."
            ok, message = self.ask("Reply with READY only.", system="Health check. Reply READY only.", timeout=5)
            if ok:
                return True, "Local AI is ready."
            if "not start" in message.lower() or "disabled" in message.lower() or "install" in message.lower():
                return False, message
            time.sleep(2)
        return False, "Local AI did not finish booting."

    def ask(self, prompt, system=None, model=None, timeout=None):
        started, message = self.ensure_started()
        if not started:
            return False, message
        payload = {
            "model": model or self.model(),
            "prompt": prompt,
            "stream": False,
            "keep_alive": f"{max(1, self.idle_shutdown_seconds() // 60)}m",
        }
        if system:
            payload["system"] = system
        request = urllib.request.Request(
            self.config.get("url") or DEFAULT_LOCAL_AI["url"],
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        self.touch()
        try:
            with self.opener(request, timeout=timeout or int(self.config.get("timeout_seconds", 120))) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            self.logger.warning("Local AI request failed: %s", exc)
            return False, "Local AI did not respond."
        self.touch()
        return True, (result.get("response") or "").strip() or "Local AI returned an empty response."

    def shutdown_if_idle(self, now=None):
        if self.last_used_at is None:
            return False
        now = int(now if now is not None else self.clock())
        if now - self.last_used_at < self.idle_shutdown_seconds():
            return False
        self.shutdown()
        return True

    def shutdown(self):
        model = self.model()
        try:
            if self.available():
                subprocess.run(["ollama", "stop", model], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass
        with self.lock:
            if self.idle_timer:
                self.idle_timer.cancel()
                self.idle_timer = None
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.process = None
            self.last_used_at = None
