"""Async subprocess helper for running scripts."""

import asyncio
import contextlib


async def run_script(
    *cmd: str,
    cwd: str,
    timeout: int = 30,
) -> str:
    """Run a subprocess and return its stdout.

    On cancellation (e.g. agent abort), the child process is killed.

    Args:
        *cmd: Command and arguments to execute.
        cwd: Working directory for the process.
        timeout: Maximum execution time in seconds.

    Returns:
        Decoded stdout output.

    Raises:
        RuntimeError: If the process exits with a non-zero return code.
        TimeoutError: If the process exceeds *timeout* seconds.
        asyncio.CancelledError: If the calling task is cancelled.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        with contextlib.suppress(OSError):
            proc.kill()
        with contextlib.suppress(asyncio.CancelledError):
            await proc.wait()
        raise

    output = stdout.decode(errors="replace")

    if proc.returncode != 0:
        raise RuntimeError(
            f"Command {cmd[0]!r} failed (exit {proc.returncode}):\n{output}"
        )

    return output
