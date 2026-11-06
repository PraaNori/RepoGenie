"""
Safe Subprocess Execution Layer for FFmpeg and FFprobe (Milestone 6, Phase 6.1).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .exceptions import FFmpegExecutionError, FFmpegNotFoundError, FFmpegTimeoutError

logger = logging.getLogger(__name__)

# Disallowed characters/patterns in argument tokens to prevent parameter injection
_PROHIBITED_TOKEN_CHARS = {"\x00", "\r", "\n"}

# Maximum bytes to buffer from stdout/stderr while process is running (512 KB)
MAX_OUTPUT_STREAM_BYTES = 512 * 1024

# Whitelisted environment variable names for safe subprocess isolation
SAFE_ENV_VARS = {
    "PATH",
    "SYSTEMROOT",
    "COMSPEC",
    "TMPDIR",
    "TMP",
    "TEMP",
    "HOME",
    "LC_ALL",
    "LC_CTYPE",
    "LANG",
}


def validate_arg_tokens(args: List[str]) -> None:
    """Verifies that individual argument tokens do not contain null bytes or control characters."""
    if not args:
        raise ValueError("Subprocess argument array cannot be empty")
    for idx, arg in enumerate(args):
        if not isinstance(arg, str):
            raise ValueError(f"Argument at index {idx} must be a string, got {type(arg).__name__}")
        for ch in _PROHIBITED_TOKEN_CHARS:
            if ch in arg:
                raise ValueError(f"Argument at index {idx} contains prohibited control character '{repr(ch)}'")


def sanitize_environment(extra_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Constructs a sanitized environment dictionary containing only essential system variables.
    Explicitly filters out API keys, tokens, or credentials.
    """
    env: Dict[str, str] = {}
    for key, val in os.environ.items():
        upper_key = key.upper()
        # Strictly ignore any key that resembles a secret
        if any(sec in upper_key for sec in ("KEY", "SECRET", "TOKEN", "PASS", "AUTH", "CRED")):
            continue
        if key in SAFE_ENV_VARS or upper_key in SAFE_ENV_VARS:
            env[key] = val

    # Ensure minimal PATH fallback
    if "PATH" not in env:
        env["PATH"] = "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"
    if "TMPDIR" not in env:
        env["TMPDIR"] = "/tmp"

    if extra_env:
        for k, v in extra_env.items():
            upper_k = k.upper()
            if not any(sec in upper_k for sec in ("KEY", "SECRET", "TOKEN", "PASS", "AUTH", "CRED")):
                env[k] = v

    return env


def kill_process_group(proc_or_pid: subprocess.Popen | int) -> None:
    """Terminates an entire process group to prevent orphan processes."""
    pid = proc_or_pid.pid if isinstance(proc_or_pid, subprocess.Popen) else proc_or_pid
    if not pid:
        return
    try:
        if os.name == "posix":
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)
        else:
            if isinstance(proc_or_pid, subprocess.Popen):
                proc_or_pid.kill()
            else:
                os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass


def _drain_stream_sync(stream, buffer: bytearray, max_bytes: int, truncated_flag: List[bool]) -> None:
    """Reads stream chunks synchronously, buffering up to max_bytes and draining excess."""
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break
            if len(buffer) < max_bytes:
                space = max_bytes - len(buffer)
                buffer.extend(chunk[:space])
                if len(chunk) > space:
                    truncated_flag[0] = True
            else:
                truncated_flag[0] = True
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def run_process_sync(
    args: List[str],
    timeout_seconds: Optional[float] = 300.0,
    cwd: Optional[Path] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> Tuple[int, str, str]:
    """
    Executes a subprocess safely using explicit argument arrays.
    Never uses shell=True.
    Limits buffered output while running and terminates the process group on timeout.
    Returns (return_code, stdout_str, stderr_str).
    """
    validate_arg_tokens(args)
    safe_env = sanitize_environment(extra_env)

    bin_name = args[0]
    resolved_cwd = str(cwd.resolve()) if cwd else None

    logger.debug("Executing safe subprocess: %s (cwd=%s, timeout=%s)", args, resolved_cwd, timeout_seconds)

    popen_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
        "cwd": resolved_cwd,
        "env": safe_env,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(args, **popen_kwargs)
    except FileNotFoundError as fnf:
        raise FFmpegNotFoundError(f"Executable not found on system path: {bin_name}") from fnf
    except Exception as exc:
        raise FFmpegExecutionError(f"Failed to start process '{bin_name}': {exc}", command=" ".join(args)) from exc

    stdout_buf = bytearray()
    stderr_buf = bytearray()
    stdout_trunc = [False]
    stderr_trunc = [False]

    t_out = threading.Thread(
        target=_drain_stream_sync,
        args=(proc.stdout, stdout_buf, MAX_OUTPUT_STREAM_BYTES, stdout_trunc),
        daemon=True,
    )
    t_err = threading.Thread(
        target=_drain_stream_sync,
        args=(proc.stderr, stderr_buf, MAX_OUTPUT_STREAM_BYTES, stderr_trunc),
        daemon=True,
    )
    t_out.start()
    t_err.start()

    try:
        ret_code = proc.wait(timeout=timeout_seconds)
        t_out.join(timeout=2.0)
        t_err.join(timeout=2.0)

        stdout_str = stdout_buf.decode("utf-8", errors="replace")
        stderr_str = stderr_buf.decode("utf-8", errors="replace")
        if stdout_trunc[0]:
            stdout_str += f"\n[RepoGenie: stdout truncated at {MAX_OUTPUT_STREAM_BYTES} bytes]"
        if stderr_trunc[0]:
            stderr_str += f"\n[RepoGenie: stderr truncated at {MAX_OUTPUT_STREAM_BYTES} bytes]"

        if ret_code != 0:
            logger.warning("Subprocess %s failed with code %d: %s", bin_name, ret_code, stderr_str[:500])
        return ret_code, stdout_str, stderr_str

    except subprocess.TimeoutExpired as te:
        kill_process_group(proc)
        try:
            proc.wait(timeout=3.0)
        except Exception:
            pass
        raise FFmpegTimeoutError(
            f"Process '{bin_name}' exceeded timeout of {timeout_seconds} seconds",
            timeout_seconds=timeout_seconds or 0.0,
        ) from te
    except Exception as exc:
        kill_process_group(proc)
        raise FFmpegExecutionError(f"Failed to execute process '{bin_name}': {exc}", command=" ".join(args)) from exc


async def _drain_stream_async(stream: asyncio.StreamReader, max_bytes: int) -> Tuple[str, bool]:
    """Reads an async stream while capping stored bytes to max_bytes to prevent memory bloat."""
    buf = bytearray()
    truncated = False
    try:
        while True:
            chunk = await stream.read(8192)
            if not chunk:
                break
            if len(buf) < max_bytes:
                space = max_bytes - len(buf)
                buf.extend(chunk[:space])
                if len(chunk) > space:
                    truncated = True
            else:
                truncated = True
    except Exception:
        pass
    text = buf.decode("utf-8", errors="replace")
    return text, truncated


async def run_process_async(
    args: List[str],
    timeout_seconds: Optional[float] = 300.0,
    cwd: Optional[Path] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> Tuple[int, str, str]:
    """
    Asynchronous subprocess execution using asyncio.create_subprocess_exec (safe execve, no shell).
    Enforces active output limits and process group cancellation.
    """
    validate_arg_tokens(args)
    safe_env = sanitize_environment(extra_env)

    bin_name = args[0]
    resolved_cwd = str(cwd.resolve()) if cwd else None

    logger.debug("Executing async safe subprocess: %s (cwd=%s)", args, resolved_cwd)

    kwargs = {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "cwd": resolved_cwd,
        "env": safe_env,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True

    try:
        proc = await asyncio.create_subprocess_exec(*args, **kwargs)
    except FileNotFoundError as fnf:
        raise FFmpegNotFoundError(f"Executable not found on system path: {bin_name}") from fnf
    except Exception as exc:
        raise FFmpegExecutionError(f"Async execution error for '{bin_name}': {exc}", command=" ".join(args)) from exc

    try:
        async def _run_and_drain():
            out_task = asyncio.create_task(_drain_stream_async(proc.stdout, MAX_OUTPUT_STREAM_BYTES))
            err_task = asyncio.create_task(_drain_stream_async(proc.stderr, MAX_OUTPUT_STREAM_BYTES))
            await proc.wait()
            (stdout_text, out_trunc), (stderr_text, err_trunc) = await asyncio.gather(out_task, err_task)
            if out_trunc:
                stdout_text += f"\n[RepoGenie: stdout truncated at {MAX_OUTPUT_STREAM_BYTES} bytes]"
            if err_trunc:
                stderr_text += f"\n[RepoGenie: stderr truncated at {MAX_OUTPUT_STREAM_BYTES} bytes]"
            return proc.returncode, stdout_text, stderr_text

        if timeout_seconds:
            ret_code, stdout, stderr = await asyncio.wait_for(_run_and_drain(), timeout=timeout_seconds)
        else:
            ret_code, stdout, stderr = await _run_and_drain()

        return ret_code if ret_code is not None else 0, stdout, stderr

    except (asyncio.TimeoutError, TimeoutError) as te:
        kill_process_group(proc.pid)
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except Exception:
            pass
        raise FFmpegTimeoutError(
            f"Async process '{bin_name}' exceeded timeout of {timeout_seconds} seconds",
            timeout_seconds=timeout_seconds or 0.0,
        ) from te
    except asyncio.CancelledError:
        kill_process_group(proc.pid)
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except Exception:
            pass
        raise
    except Exception as exc:
        kill_process_group(proc.pid)
        if isinstance(exc, (FFmpegNotFoundError, FFmpegTimeoutError)):
            raise
        raise FFmpegExecutionError(f"Async execution error for '{bin_name}': {exc}", command=" ".join(args)) from exc
