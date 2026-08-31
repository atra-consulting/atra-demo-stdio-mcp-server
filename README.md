# Atra Demo STDIO MCP Server

A small Model Context Protocol server for demo purposes. Speaks JSON-RPC over
**stdio** and exposes 5 tools.

Built with the official Python SDK (`mcp` 2.1+, `MCPServer` API). Dependencies
are declared inline (PEP 723), so `uv` installs them on the fly — no venv setup.

## Start it in MCP Inspector

Use the launcher — it resolves `uv` and the script to absolute paths itself, so
it works no matter what working directory or PATH the Inspector runs with:

```bash
npx @modelcontextprotocol/inspector /Users/benjamin/Desktop/demo-mcp-server/run-server.sh
```

Or launch the Inspector bare (`npx @modelcontextprotocol/inspector`) and fill in:

| Field     | Value                                                  |
| --------- | ------------------------------------------------------ |
| Transport | `STDIO`                                                |
| Command   | `/Users/benjamin/Desktop/demo-mcp-server/run-server.sh` |
| Arguments | *(leave empty)*                                        |

Then hit **Connect** → the Tools tab fills up.

### If you get "Connection closed"

That is the Inspector's generic message for *the process died before speaking
MCP*. The two causes, both fixed by the launcher above:

1. **Relative paths.** The Inspector spawns the server from its own working
   directory, not yours. `uv run server.py` fails with
   `Failed to spawn: server.py` → connection closed. Always use absolute paths.
2. **`uv` not on PATH.** It lives in `/opt/homebrew/bin`, which GUI-launched
   processes usually do not inherit. Command `uv` then fails with ENOENT.

To see the real error instead of the generic one, run the same command in a
terminal — it prints the underlying failure:

```bash
npx @modelcontextprotocol/inspector --cli /Users/benjamin/Desktop/demo-mcp-server/run-server.sh --method tools/list
```

## Watching the protocol (for the workshop)

Every JSON-RPC frame crossing the wire is teed into a logfile, in both
directions, labelled by message type. Open a second terminal and run:

```bash
tail -f /Users/benjamin/Desktop/demo-mcp-server/mcp-demo.log
```

Then drive the server from the Inspector and the traffic scrolls past live:

```
14:32:55.510 --> REQUEST      initialize                   id=0
14:32:55.510 <-- RESPONSE     initialize                   id=0  (0.6 ms)
14:32:55.514 --> NOTIFICATION notifications/initialized
14:32:55.515 --> REQUEST      tools/list                   id=1
14:32:55.515 <-- RESPONSE     tools/list                   id=1  (0.5 ms)
14:32:55.518 --> REQUEST      tools/call                   id=2
14:32:55.559 <-- NOTIFICATION notifications/message
14:32:55.766 <-- RESPONSE     tools/call                   id=2  (1209.8 ms)
14:33:07.132 <-- ERROR        does/notExist                id=2  (0.4 ms)
```

- `-->` is client to server, `<--` is server to client.
- Frames are classified as **REQUEST** (has `method` + `id`), **NOTIFICATION**
  (`method`, no `id` -- fire and forget, never answered), **RESPONSE**, or
  **ERROR**.
- Responses are correlated back to their request, so they show the method name
  they answer plus the round-trip time.
- Under each summary line sits the full JSON payload, indented.

### Log settings

Edit the block at the top of `run-server.sh`:

| Variable                | Values                    | Meaning                            |
| ----------------------- | ------------------------- | ---------------------------------- |
| `MCP_DEMO_LOG`          | path                      | Where to write (default `mcp-demo.log` here) |
| `MCP_DEMO_LOG_PAYLOAD`  | `full` / `compact` / `none` | How much of each frame to print  |
| `MCP_DEMO_LOG_TRUNCATE` | `0` / `1`                 | `1` starts a fresh log each run    |
| `MCP_DEMO_LOG_STDERR`   | `headers` / `full` / `off` | Mirror the trace to stderr, i.e. into the Inspector's server console |

They must be set **in the script**, not in your shell: MCP hosts sanitize the
environment before spawning a server, so your exported variables never arrive.
(Running `run-server.sh` directly from a terminal, your env does win.)

For a summary-only view during a live demo, `compact` mode plus:

```bash
tail -f mcp-demo.log | grep -E '\-\->|<\-\-'
```

### Watching the trace inside MCP Inspector

The Inspector spawns a stdio server with its **stderr piped** into the UI and
shows those lines in the **Console** tab (headed "Server Console"), alongside
Logs / Protocol / Network. That tab is fed *only* by stderr — nothing else lands
there — which is exactly what `MCP_DEMO_LOG_STDERR` writes the protocol trace to:

| Value               | Inspector console shows                              |
| ------------------- | ---------------------------------------------------- |
| `headers` (default) | one summary line per frame — readable during a demo   |
| `full`              | summary lines **plus** the indented JSON payloads     |
| `off`               | nothing; the logfile stays the only sink              |

The logfile always gets the full `MCP_DEMO_LOG_PAYLOAD` treatment regardless —
the stderr mirror only decides how much of it is echoed.

Three things to know:

- stderr is never the protocol wire, so mirroring cannot corrupt stdio. (The
  server also points `sys.stdout` at stderr, so a stray `print()` is safe too.)
- The trace only appears in a server process spawned **after** the setting
  changed. If the Inspector is already connected, hit Reconnect/Restart — the
  running child process keeps the environment and code it started with.
- The **Console** tab is *not* the **Logs** tab. Logs is fed by MCP's `logging`
  capability: the `countdown` tool's `ctx.info(...)` sends `notifications/message`,
  which the Inspector renders as server notifications — but that capability is
  deprecated (SEP-2577, 2026-07-28) and on current protocol versions delivery is
  a per-request opt-in the client has to ask for. The stderr mirror is the route
  that always works.

### Protocol points worth making

- **Notifications get no reply.** `notifications/initialized` and
  `notifications/message` appear with no matching response line.
- **Tool errors are not protocol errors.** `roll_dice` with `sides: 1` comes
  back as a normal RESPONSE carrying `"isError": true` -- the call succeeded at
  the protocol level, the *tool* failed. Contrast with calling an unknown
  method, which produces a real JSON-RPC **ERROR** frame.
- **Version negotiation** is visible in the very first exchange: the client
  proposes a `protocolVersion`, the server answers with the one it will use.
- **Capabilities** are announced once, at initialize, and decide which tabs the
  Inspector even shows.
- **Progress** notifications only flow when the client sends a `progressToken`
  with the call. The Inspector UI does; the `--cli` mode does not -- which is
  itself a nice thing to show.

## How the logging works

`stdout` *is* the protocol channel for a stdio server, so nothing may print
there. The server therefore:

1. passes its own tee wrappers into `stdio_server(stdin=..., stdout=...)`, which
   log each raw line before handing it on -- this is why the log shows the true
   wire bytes rather than a reconstruction;
2. repoints `sys.stdout` at stderr, so a stray `print()` in a handler can never
   corrupt the stream;
3. logs from tools via `ctx.info()`, which is a protocol notification and shows
   up both in the logfile and in the Inspector's notification pane.

## What to show off

**Tools**
- `add(a, b)` — trivial, good first click
- `echo(text, upper=false)` — optional argument
- `roll_dice(sides=6, count=1)` — returns structured JSON, plus input validation
  (try `sides: 1` to show a clean tool error)
- `current_time(timezone_note="local")`
- `countdown(steps)` — **the good one**: emits progress notifications and server
  logs per step, so the Inspector's progress bar and *Server Notifications* pane
  light up live. Try `steps: 10`, and cancel mid-run to show cancellation.

## Run it manually

```bash
uv run /Users/benjamin/Desktop/demo-mcp-server/server.py
```

A healthy stdio server prints **nothing** and just waits on stdin. Any stray
stdout output would corrupt the protocol stream — that's why the demo logs
through `ctx.info()` (a protocol notification) instead of `print()`.
