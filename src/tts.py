import base64
import subprocess


class TTSEngine:
    def __init__(self, rate: int = 175):
        # Convert words-per-minute to System.Speech rate (-10 to +10, default 0 ≈ 175 wpm)
        ps_rate = max(-10, min(10, round((rate - 175) / 25)))

        # PowerShell worker using System.Speech.SpeechSynthesizer (reliable on Windows;
        # pyttsx3 via win32com/SAPI5 fails silently in subprocess COM contexts)
        worker_script = (
            "Add-Type -AssemblyName System.Speech\n"
            "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
            f"$synth.Rate = {ps_rate}\n"
            "[Console]::InputEncoding  = [System.Text.Encoding]::UTF8\n"
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
            "[Console]::Out.WriteLine('READY')\n"
            "[Console]::Out.Flush()\n"
            "while ($true) {\n"
            "    $line = [Console]::In.ReadLine()\n"
            "    if ($null -eq $line) { break }\n"
            "    if ($line.Trim()) {\n"
            "        try {\n"
            "            $synth.Speak($line)\n"
            "        } catch {\n"
            "            [Console]::Error.WriteLine('[TTS] ' + $_.Exception.Message)\n"
            "            [Console]::Error.Flush()\n"
            "        }\n"
            "    }\n"
            "    [Console]::Out.WriteLine('DONE')\n"
            "    [Console]::Out.Flush()\n"
            "}\n"
        )
        # -EncodedCommand avoids shell-quoting issues with multi-line scripts
        encoded = base64.b64encode(worker_script.encode('utf-16-le')).decode('ascii')
        self._proc = subprocess.Popen(
            ['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding='utf-8',
        )
        ready = self._proc.stdout.readline()
        if ready.strip() != "READY":
            self._proc.wait()
            raise RuntimeError(
                f"TTS worker failed to initialize "
                f"(returncode={self._proc.returncode}, got={ready!r})"
            )

    def speak(self, text: str) -> None:
        if not text or not text.strip():
            return
        if self._proc.poll() is not None:
            raise RuntimeError(
                f"TTS subprocess has exited (returncode={self._proc.returncode})"
            )
        line = text.replace("\n", " ").replace("\r", " ")
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()
        response = self._proc.stdout.readline()
        if not response:
            self._proc.wait()
            raise RuntimeError(
                f"TTS subprocess died during speech "
                f"(returncode={self._proc.returncode})"
            )
