import json
import shutil
import subprocess
import threading

VOICE_SYSTEM_PROMPT = (
    "Your final response will be spoken aloud through text-to-speech. "
    "Keep it under 3 sentences, plain prose, no markdown or code unless "
    "asked to read code."
)

# First matching key of a tool_use input becomes the console activity hint.
_ACTIVITY_INPUT_KEYS = ("description", "file_path", "path", "command", "pattern", "query", "url", "program")


class ClaudeCodeSession:
    """Headless Claude Code sessions via streaming `claude -p` invocations.

    Continuity across utterances comes from --resume with the session id
    captured from the stream's init event. send() never raises — every
    failure returns a spoken-safe string. Tool activity events are printed
    as they arrive so the console shows what the agent is doing live.
    cancel() (thread-safe) kills any in-flight CLI process; the pending
    send() then returns "" so callers can discard it silently.
    """

    def __init__(
        self,
        model: str | None = None,
        permission_mode: str = "acceptEdits",
        max_turns: int = 25,
        task_timeout_seconds: int = 600,
    ):
        self._model = model
        self._permission_mode = permission_mode
        self._max_turns = max_turns
        self._timeout = task_timeout_seconds
        self._workdir: str | None = None
        self._session_id: str | None = None
        self._proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()
        self._cancelled = False
        self._timed_out = False

    def start(self, workdir: str) -> None:
        self._workdir = workdir
        self._session_id = None
        self._cancelled = False

    def send(self, text: str) -> str:
        try:
            cli = shutil.which("claude")
            if cli is None:
                return "Claude Code isn't installed on this unit."
            cmd = [
                cli, "-p", text,
                "--output-format", "stream-json",
                "--verbose",  # the CLI requires it for stream-json with -p
                "--permission-mode", self._permission_mode,
                "--add-dir", self._workdir,
                "--max-turns", str(self._max_turns),
                "--append-system-prompt", VOICE_SYSTEM_PROMPT,
            ]
            if self._model:
                cmd += ["--model", self._model]
            if self._session_id:
                cmd += ["--resume", self._session_id]

            self._timed_out = False
            with self._proc_lock:
                if self._cancelled:
                    return ""
                # stderr merges into stdout: a separate unread pipe could fill
                # and deadlock the CLI mid-stream; non-JSON lines are kept as
                # the failure detail instead.
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=self._workdir,
                )
                proc = self._proc

            watchdog = threading.Timer(self._timeout, self._kill_for_timeout)
            watchdog.daemon = True
            watchdog.start()
            result_text = None
            tail: list[str] = []
            try:
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        tail.append(line)
                        del tail[:-5]
                        continue
                    self._handle_event(event)
                    if event.get("type") == "result":
                        result_text = event.get("result")
            finally:
                watchdog.cancel()
                proc.wait()
                with self._proc_lock:
                    self._proc = None

            if self._timed_out:
                return "That task timed out."
            if self._cancelled:
                return ""
            if proc.returncode != 0:
                detail = tail[-1][:120] if tail else f"exit code {proc.returncode}"
                return f"Claude Code failed ({detail})."
            return str(result_text) if result_text else "Claude finished but returned no text."
        except Exception as e:
            return f"Claude Code failed ({e})."

    def cancel(self) -> None:
        """Kill any in-flight CLI process. Safe to call from another thread;
        the session stays cancelled until the next start()."""
        self._cancelled = True
        self._kill_proc()

    def stop(self) -> None:
        self.cancel()
        self._session_id = None
        self._workdir = None

    # ------------------------------------------------------------------ #

    def _handle_event(self, event: dict) -> None:
        etype = event.get("type")
        if etype in ("system", "result") and event.get("session_id"):
            self._session_id = event["session_id"]
        if etype == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name", "tool")
                    hint = self._describe_input(block.get("input") or {})
                    print(f"[Claude] > {name}: {hint}" if hint else f"[Claude] > {name}")

    @staticmethod
    def _describe_input(tool_input: dict) -> str:
        for key in _ACTIVITY_INPUT_KEYS:
            value = tool_input.get(key)
            if value:
                return str(value)[:100]
        return ""

    def _kill_for_timeout(self) -> None:
        self._timed_out = True
        self._kill_proc()

    def _kill_proc(self) -> None:
        with self._proc_lock:
            proc = self._proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
