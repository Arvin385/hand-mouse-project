"""Background speech-to-text service.

Starts the C++ ``voice_service`` subprocess, reads newline-delimited
transcription text from a file descriptor, and exposes it via a thread-safe
queue.

Usage
-----
    from voice.src.stt.stt import VoiceTranscriber, transcriber

    # Use the default instance
    transcriber.start()
    text = transcriber.get_transcription(timeout=5.0)
    transcriber.stop()

    # Or create your own
    stt = VoiceTranscriber(
        model="/path/to/ggml-base.en.bin",
        vad_model="/path/to/silero_vad.onnx",
    )
    stt.start()
    ...

Environment variables
---------------------
STT_WHISPER_MODEL    Path to the whisper model (.bin)
STT_VAD_MODEL        Path to the Silero VAD model (.onnx)
STT_MODEL            Same as STT_WHISPER_MODEL (alias)
STT_GPU              Enable GPU: "1" / "true" (default: "1")
STT_THREADS          Number of threads (default: "2")
STT_LANGUAGE         Language code (default: "auto")
"""

from __future__ import annotations

import os
import subprocess
import threading
from queue import Queue, Empty
from typing import Optional


# ---------------------------------------------------------------------------
# Defaults — overridable via env vars
# ---------------------------------------------------------------------------

_WHISPER_MODEL = os.environ.get("STT_WHISPER_MODEL") or os.environ.get(
    "STT_MODEL", ""
)
_VAD_MODEL = os.environ.get("STT_VAD_MODEL", "")
_GPU = os.environ.get("STT_GPU", "1").lower() in ("1", "true", "yes")
_THREADS = int(os.environ.get("STT_THREADS", "2"))
_LANGUAGE = os.environ.get("STT_LANGUAGE", "auto")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SERVICE_NAME = "voice_service"


def _resolve_service_path() -> str:
    """Return the path to the voice_service binary.

    Checks the build directory adjacent to this source file, then the
    system PATH.  Raises ``RuntimeError`` if the binary cannot be found.
    """
    # Directory where this source file lives (voice/src/stt/)
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    # Build output is typically at voice/src/stt/build/bin/
    build_bin = os.path.join(pkg_dir, "build", "bin", _SERVICE_NAME)
    if os.path.isfile(build_bin):
        return build_bin

    # Fallback: look in the repo root's build directory
    repo_root = os.path.abspath(os.path.join(pkg_dir, "..", "..", ".."))
    repo_bin = os.path.join(repo_root, "build", "bin", _SERVICE_NAME)
    if os.path.isfile(repo_bin):
        return repo_bin

    # Last resort: PATH lookup
    found = subprocess._executable_path(_SERVICE_NAME) if hasattr(
        subprocess, "_executable_path"
    ) else None
    if found:
        return found

    raise RuntimeError(
        f"{_SERVICE_NAME} binary not found.\n"
        f"  Searched:\n"
        f"    {build_bin}\n"
        f"    {repo_bin}\n"
        f"  Build it with: cmake --build voice/src/stt/build"
    )


def _drain_loop(
    pipe_fd: int,
    queue: Queue,
    running: threading.Event,
) -> None:
    """Background thread: read newline-delimited text from the pipe FD
    and put each line into *queue*.

    The thread exits when the pipe closes (C++ process exits) or when
    *running* is set.
    """
    try:
        fp = os.fdopen(pipe_fd, "r")
    except OSError as exc:
        # Shouldn't happen — fd was valid when Popen created it
        return

    while running.is_set():
        try:
            line = fp.readline()
            if not line:
                # Pipe closed — C++ process exited
                break
            text = line.strip()
            if text:
                queue.put(text)
        except (OSError, ValueError):
            # Pipe may have been closed from the other end
            break

    fp.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class VoiceTranscriber:
    """Manages the C++ ``voice_service`` subprocess and its output queue.

    Attributes
    ----------
    model_path : str
        Path to the whisper model binary.
    vad_model_path : str
        Path to the Silero VAD model (optional).
    use_gpu : bool
        Whether to use CUDA GPU acceleration.
    threads : int
        Number of inference threads.
    language : str
        Language code (e.g. "en", "auto").
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        vad_model_path: Optional[str] = None,
        use_gpu: Optional[bool] = None,
        threads: Optional[int] = None,
        language: Optional[str] = None,
    ):
        self.model_path = model_path or _WHISPER_MODEL or ""
        self.vad_model_path = vad_model_path or _VAD_MODEL or ""
        self.use_gpu = use_gpu if use_gpu is not None else _GPU
        self.threads = threads if threads is not None else _THREADS
        self.language = language or _LANGUAGE

        self._service_path = _resolve_service_path()
        self._process: Optional[subprocess.Popen] = None
        self._queue: Queue = Queue(maxsize=0)
        self._drain_thread: Optional[threading.Thread] = None
        self._running = threading.Event()

    @property
    def is_running(self) -> bool:
        """Whether the voice_service process is currently active."""
        return (
            self._running.is_set()
            and self._process is not None
            and self._process.poll() is None
        )

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    def start(self) -> None:
        """Start the voice_service subprocess and drain thread.

        Raises
        ------
        RuntimeError
            If the subprocess fails to start or the pipe cannot be created.
        """
        if self.is_running:
            return

        # Build command-line arguments
        args = [
            "--model", self.model_path,
            "--threads", str(self.threads),
            "--lang", self.language,
            "--log", "info",
        ]
        if self.vad_model_path:
            args.extend(["--vad", self.vad_model_path])
        if self.use_gpu:
            args.append("--gpu")

        # Create a pipe: parent reads from stdout of child
        read_fd, write_fd = os.pipe()

        try:
            # Launch the C++ service — it writes to write_fd
            self._process = subprocess.Popen(
                args=[self._service_path] + args,
                stdout=write_fd,
                stderr=subprocess.DEVNULL,
                pass_fds=[write_fd],
            )
        except FileNotFoundError as exc:
            os.close(read_fd)
            os.close(write_fd)
            raise RuntimeError(
                f"Cannot start {_SERVICE_NAME}: {exc}\n"
                f"  Path: {self._service_path}"
            ) from exc
        except OSError as exc:
            os.close(read_fd)
            os.close(write_fd)
            raise RuntimeError(
                f"Failed to start {_SERVICE_NAME}: {exc}"
            ) from exc

        # Close write end in parent — only child writes
        os.close(write_fd)

        # Start the drain thread
        self._running.set()
        self._drain_thread = threading.Thread(
            target=_drain_loop,
            args=(read_fd, self._queue, self._running),
            daemon=True,
            name="stt-drain",
        )
        self._drain_thread.start()

    def stop(self) -> None:
        """Stop the voice_service subprocess and drain thread."""
        if not self.is_running:
            return

        # Stop the drain loop
        self._running.clear()

        # Terminate the C++ process
        if self._process is not None:
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
            except OSError:
                pass
            self._process = None

        # Wait for drain thread to finish
        if self._drain_thread is not None:
            self._drain_thread.join(timeout=2)
            self._drain_thread = None

    # -------------------------------------------------------------------
    # Queue access
    # -------------------------------------------------------------------

    def get_transcription(self, timeout: Optional[float] = None) -> Optional[str]:
        """Get the next transcription from the queue.

        Parameters
        ----------
        timeout : float or None
            Maximum seconds to wait.  ``None`` blocks indefinitely.

        Returns
        -------
        str or None
            The transcribed text, or ``None`` if the queue is empty and
            the process has exited, or if *timeout* expires.

        Raises
        ------
        RuntimeError
            If the voice_service process has crashed unexpectedly.
        """
        # Check if process is alive
        if self._process is not None and self._process.poll() is not None:
            rc = self._process.returncode
            raise RuntimeError(
                f"voice_service exited unexpectedly (code {rc})"
            )

        try:
            return self._queue.get(timeout=timeout)
        except Empty:
            return None

    def get_all_transcriptions(self) -> list[str]:
        """Return all currently available transcriptions (non-blocking).

        Returns
        -------
        list[str]
            A list of queued transcriptions.  Returns an empty list if
            no transcriptions are available.
        """
        results = []
        while True:
            try:
                results.append(self._queue.get_nowait())
            except Empty:
                break
        return results

    # -------------------------------------------------------------------
    # Context manager
    # -------------------------------------------------------------------

    def __enter__(self) -> "VoiceTranscriber":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()


# ---------------------------------------------------------------------------
# Default instance — for simple usage
# ---------------------------------------------------------------------------

transcriber = VoiceTranscriber()

# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def get_next_transcription(timeout: Optional[float] = None) -> Optional[str]:
    """Get the next transcription using the default instance.

    Parameters
    ----------
    timeout : float or None
        Maximum seconds to wait.  ``None`` blocks indefinitely.

    Returns
    -------
    str or None
        The transcribed text, or ``None`` on timeout or process exit.

    Raises
    ------
    RuntimeError
        If the voice_service process has crashed.
    """
    return transcriber.get_transcription(timeout=timeout)
