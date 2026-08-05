import json
import shutil
import subprocess

VOICE_SYSTEM_PROMPT = (
    "Your final response will be spoken aloud through text-to-speech. "
    "Keep it under 3 sentences, plain prose, no markdown or code unless "
    "asked to read code."
)


class ClaudeCodeSession:
    """Headless Claude Code sessions via one-shot `claude -p` invocations.

    Continuity across utterances comes from --resume with the session id
    captured on the first call. send() never raises — every failure
    returns a spoken-safe string.
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

    def start(self, workdir: str) -> None:
        self._workdir = workdir
        self._session_id = None

    def send(self, text: str) -> str:
        try:
            cli = shutil.which("claude")
            if cli is None:
                return "Claude Code isn't installed on this unit."
            cmd = [
                cli, "-p", text,
                "--output-format", "json",
                "--permission-mode", self._permission_mode,
                "--add-dir", self._workdir,
                "--max-turns", str(self._max_turns),
                "--append-system-prompt", VOICE_SYSTEM_PROMPT,
            ]
            if self._model:
                cmd += ["--model", self._model]
            if self._session_id:
                cmd += ["--resume", self._session_id]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self._workdir,
                timeout=self._timeout,
            )
            if proc.returncode != 0:
                snippet = (proc.stderr or "").strip().splitlines()
                detail = snippet[-1][:120] if snippet else f"exit code {proc.returncode}"
                return f"Claude Code failed ({detail})."
            data = json.loads(proc.stdout)
            self._session_id = data.get("session_id", self._session_id)
            result = data.get("result")
            return str(result) if result else "Claude finished but returned no text."
        except subprocess.TimeoutExpired:
            return "That task timed out."
        except Exception as e:
            return f"Claude Code failed ({e})."

    def stop(self) -> None:
        self._session_id = None
        self._workdir = None
