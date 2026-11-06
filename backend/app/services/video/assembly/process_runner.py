"""
Safe Subprocess Execution Layer for FFmpeg and FFprobe (Milestone 6, Phase 6.1).
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .exceptions import FFmpegExecutionError, FFmpegNotFoundError, FFmpegTimeoutError

logger = logging.getLogger(__name__)

# Disallowed characters/patterns in argument tokens to prevent parameter injection
_PROHIBITED_TOKEN_CHARS = {"\x00", "\r", "\n"}


def validate_arg_tokens(args: List[str]) -> None:
    """Verifies that individual argument tokens do not contain null bytes or control characters."""
    for idx, arg in enumerate(args):
        if not isinstance(arg, str):
            raise ValueError(f"Argument at index {idx} must be a string, got {type(arg).__name__}")
        for ch in _PROHIBITED_TOKEN_CHARS:
            if ch in arg:
                raise ValueError(f"Argument at index {idx} contains prohibited control character '{repr(ch)}'")


def run_process_sync(
    args: List[str],
    timeout_seconds: Optional[float] = 300.0,
    cwd: Optional[Path] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> Tuple[int, str, str]:
    """
    Executes a subprocess safely using explicit argument arrays.
    Never uses shell=True.
    Returns (return_code, stdout_str, stderr_str).
    """
    validate_arg_tokens(args)

    # Sanitize environment: clone system PATH and essential vars, never dump raw server secrets
    safe_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }
    if extra_env:
        safe_env.update(extra_env)

    # Binary name/path is args[0]
    bin_name = args[0]
    resolved_cwd = str(cwd.resolve()) if cwd else None

    logger.debug("Executing safe subprocess: %s (cwd=%s, timeout=%s)", args, resolved_cwd, timeout_seconds)

    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            cwd=resolved_cwd,
            env=safe_env,
        )
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
        ret_code = proc.returncode

        if ret_code != 0:
            logger.warning("Subprocess %s failed with code %d: %s", bin_name, ret_code, stderr[:500])
        return ret_code, stdout, stderr

    except FileNotFoundError as fnf:
        raise FFmpegNotFoundError(f"Executable not found on system path: {bin_name}") from fnf
    except subprocess.TimeoutExpired as te:
        try:
            proc.kill()
            stdout, stderr = proc.communicate(timeout=5.0)
        except Exception:
            pass
        raise FFmpegTimeoutError(
            f"Process '{bin_name}' exceeded timeout of {timeout_seconds} seconds",
            timeout_seconds=timeout_seconds or 0.0,
        ) from te
    except Exception as exc:
        raise FFmpegExecutionError(f"Failed to execute process '{bin_name}': {exc}", command=" ".join(args)) from exc


async def run_process_async(
    args: List[str],
    timeout_seconds: Optional[float] = 300.0,
    cwd: Optional[Path] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> Tuple[int, str, str]:
    """
    Asynchronous subprocess execution using asyncio.create_subprocess_exec (safe execve, no shell).
    """
    validate_arg_tokens(args)

    safe_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }
    if extra_env:
        safe_env.update(extra_env)

    bin_name = args[0]
    resolved_cwd = str(cwd.resolve()) if cwd else None

    logger.debug("Executing async safe subprocess: %s (cwd=%s)", args, resolved_cwd)

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=resolved_cwd,
            env=safe_env,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds,
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            ret_code = proc.returncode if proc.returncode is not None else 0
            return ret_code, stdout, stderr
        except asyncio.TimeoutError as te:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            raise FFmpegTimeoutError(
                f"Async process '{bin_name}' exceeded timeout of {timeout_seconds} seconds",
                timeout_seconds=timeout_seconds or 0.0,
            ) from te

    except FileNotFoundError as fnf:
        raise FFmpegNotFoundError(f"Executable not found on system path: {bin_name}") from fnf
    except Exception as exc:
        if isinstance(exc, (FFmpegNotFoundError, FFmpegTimeoutError)):
            raise
        raise FFmpegExecutionError(f"Async execution error for '{bin_name}': {exc}", command=" ".join(args)) from exc
