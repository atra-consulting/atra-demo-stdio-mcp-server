#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.1.1"]
# ///
"""Atra Demo STDIO MCP Server (stdio transport) with full protocol logging.

Every JSON-RPC frame crossing the wire is written to a logfile, labelled by
direction and message type, so a workshop audience can watch the protocol live:

    tail -f ~/Desktop/demo-mcp-server/mcp-demo.log

Environment variables:
    MCP_DEMO_LOG          logfile path (default: mcp-demo.log next to this file)
    MCP_DEMO_LOG_PAYLOAD  full (default) | compact | none
    MCP_DEMO_LOG_TRUNCATE 1 to start a fresh logfile on each run
    MCP_DEMO_LOG_STDERR   headers (default) | full | off -- mirror the trace to
                          stderr, which the MCP Inspector shows in its server
                          console pane (stdio servers only)

Run standalone:   uv run server.py
Run in Inspector: npx @modelcontextprotocol/inspector ./run-server.sh
"""

from __future__ import annotations

import io
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.stdio import stdio_server

# ==========================================================================
# Protocol logging
# ==========================================================================

LOG_PATH = Path(os.environ.get("MCP_DEMO_LOG") or Path(__file__).with_name("mcp-demo.log"))
PAYLOAD_MODE = os.environ.get("MCP_DEMO_LOG_PAYLOAD", "full").lower()
TRUNCATE = os.environ.get("MCP_DEMO_LOG_TRUNCATE") == "1"
# Mirror to stderr: the Inspector pipes a stdio server's stderr into its server
# console, so the same trace shows up there. "headers" keeps that pane readable
# by mirroring only the summary lines; the logfile still gets full payloads.
STDERR_MODE = os.environ.get("MCP_DEMO_LOG_STDERR", "headers").lower()

# Inbound = client -> server, outbound = server -> client.
IN, OUT = "-->", "<--"


class ProtocolLog:
    """Writes a human-readable trace of the JSON-RPC wire traffic."""

    def __init__(self, path: Path) -> None:
        self._file = path.open("w" if TRUNCATE else "a", encoding="utf-8")
        # id -> (method, monotonic start) so a response can name its request.
        self._pending: dict[str, tuple[str, float]] = {}

    # -- low-level -------------------------------------------------------

    def _write(self, text: str, *, echo: bool = True) -> None:
        self._file.write(text)
        self._file.flush()  # keep `tail -f` live
        if echo and STDERR_MODE != "off":
            # stderr is never the protocol wire, so this cannot corrupt stdio.
            sys.stderr.write(text)
            sys.stderr.flush()

    def note(self, text: str) -> None:
        """A free-form line that is not a protocol frame."""
        self._write(f"{datetime.now():%H:%M:%S.%f}"[:-3] + f"  ..  {text}\n")

    def banner(self, text: str) -> None:
        self._write(f"\n{'=' * 78}\n{datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n{'=' * 78}\n")

    # -- frames ----------------------------------------------------------

    def frame(self, direction: str, raw: str) -> None:
        """Log one JSON-RPC frame exactly as it crossed the wire."""
        raw = raw.strip()
        if not raw:
            return
        try:
            msg: Any = json.loads(raw)
        except ValueError:
            self.note(f"{direction} unparseable frame: {raw[:200]}")
            return

        for part in msg if isinstance(msg, list) else [msg]:  # batches
            self._frame_one(direction, part)

    def _frame_one(self, direction: str, msg: dict[str, Any]) -> None:
        msg_id = msg.get("id")
        key = str(msg_id)
        method = msg.get("method")
        detail = ""

        if method is not None and msg_id is not None:
            kind = "REQUEST"
            self._pending[key] = (method, time.monotonic())
        elif method is not None:
            kind = "NOTIFICATION"
        else:
            # A response: recover the method name from the matching request.
            kind = "ERROR" if "error" in msg else "RESPONSE"
            origin, started = self._pending.pop(key, (None, None))
            method = origin or "?"
            if started is not None:
                detail = f"  ({(time.monotonic() - started) * 1000:.1f} ms)"

        stamp = f"{datetime.now():%H:%M:%S.%f}"[:-3]
        ident = f"id={msg_id}" if msg_id is not None else ""
        self._write(f"{stamp} {direction} {kind:<12} {method:<28} {ident}{detail}".rstrip() + "\n")

        if PAYLOAD_MODE == "none":
            return
        echo_payload = STDERR_MODE == "full"
        if PAYLOAD_MODE == "compact":
            body = json.dumps(msg, ensure_ascii=False)
            self._write(f"        {body[:400]}{' ...' if len(body) > 400 else ''}\n", echo=echo_payload)
        else:
            body = json.dumps(msg, indent=2, ensure_ascii=False)
            self._write("".join(f"        {line}\n" for line in body.splitlines()), echo=echo_payload)

    def close(self) -> None:
        self._file.close()


class LoggingStdin:
    """Tees every inbound line to the log, then hands it to the transport."""

    def __init__(self, stream: Any, log: ProtocolLog) -> None:
        self._stream, self._log = stream, log

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        async for line in self._stream:
            self._log.frame(IN, line)
            yield line


class LoggingStdout:
    """Tees every outbound frame to the log, then writes it to the wire."""

    def __init__(self, stream: Any, log: ProtocolLog) -> None:
        self._stream, self._log = stream, log

    async def write(self, data: str) -> None:
        self._log.frame(OUT, data)
        await self._stream.write(data)

    async def flush(self) -> None:
        await self._stream.flush()


# ==========================================================================
# The server
# ==========================================================================

mcp = MCPServer("Atra Demo STDIO MCP Server", version="1.0.0")


# --- Tools ----------------------------------------------------------------


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers together."""
    return a + b


@mcp.tool()
def echo(text: str, upper: bool = False) -> str:
    """Echo the given text back, optionally in upper case."""
    return text.upper() if upper else text


@mcp.tool()
def roll_dice(sides: int = 6, count: int = 1) -> dict:
    """Roll one or more dice and return the individual rolls plus their total."""
    if sides < 2:
        raise ValueError("A die needs at least 2 sides.")
    if not 1 <= count <= 100:
        raise ValueError("count must be between 1 and 100.")
    rolls = [random.randint(1, sides) for _ in range(count)]
    return {"rolls": rolls, "total": sum(rolls), "sides": sides}


@mcp.tool()
def current_time(timezone_note: str = "local") -> str:
    """Return the server's current date and time as an ISO-8601 string."""
    return f"{datetime.now().isoformat(timespec='seconds')} ({timezone_note})"


@mcp.tool()
async def countdown(steps: int, ctx: Context) -> dict[str, int]:
    """Count down over N steps, emitting progress and log notifications.

    Nice for demoing the Inspector's progress bar and server-log panel -- and
    every notification shows up in the logfile as a server-to-client frame.
    """
    if not 1 <= steps <= 20:
        raise ValueError("steps must be between 1 and 20.")
    try:
        for i in range(1, steps + 1):
            await ctx.report_progress(float(i), float(steps), f"step {i}/{steps}")
            await ctx.info(f"Working... step {i} of {steps}")
            await anyio.sleep(0.4)
    except anyio.get_cancelled_exc_class():
        # Client abandoned the call -- unwind cleanly.
        raise
    return {"completed": steps, "total": steps}


# ==========================================================================
# Entry point
# ==========================================================================


async def serve() -> None:
    """Serve over stdio with both directions of the wire teed into the log."""
    log = ProtocolLog(LOG_PATH)
    log.banner(f"session start -- pid {os.getpid()} -- transport: stdio")
    log.note(f"payload mode: {PAYLOAD_MODE}   '{IN}' = client to server, '{OUT}' = server to client")
    log.note(f"stderr mirror: {STDERR_MODE}   (the Inspector shows stderr in its server console)")

    # Grab the real stdout (the protocol wire) before anything else can use it,
    # then point sys.stdout at stderr so a stray print() can never corrupt it.
    wire_in = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    wire_out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stdout = sys.stderr

    lowlevel = getattr(mcp, "_lowlevel_server", None)
    if lowlevel is None:  # SDK internals moved -- serve without wire logging
        log.note("WARNING: cannot reach the low-level server; wire logging disabled")
        await mcp.run_stdio_async()
        return

    try:
        async with stdio_server(
            stdin=LoggingStdin(anyio.wrap_file(wire_in), log),
            stdout=LoggingStdout(anyio.wrap_file(wire_out), log),
        ) as (read_stream, write_stream):
            # This demo is tools-only: drop the prompts/resources capabilities the
            # SDK advertises by default, so those Inspector tabs stay away.
            init_options = lowlevel.create_initialization_options()
            init_options.capabilities.prompts = None
            init_options.capabilities.resources = None
            await lowlevel.run(read_stream, write_stream, init_options)
    finally:
        log.banner("session end")
        log.close()


if __name__ == "__main__":
    anyio.run(serve)
