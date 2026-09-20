# Zcrafter Bridge

Give AI Agents real access to your mainframe and keep it from changing anything you haven't approved.

<img width="3000" height="1027" alt="6770AD52-6CF4-4300-9BF8-2D1A6C96FB9C" src="https://github.com/user-attachments/assets/98dc50c8-0752-4c3a-a491-0d8af2311460" />


## What's an MCP server?

MCP is how AI Agents talks to outside systems. An MCP server hands AI a set of tools it can call. Bridge is an MCP server whose tools are your mainframe - datasets, members, jobs, spool.

Bridge is a network service: the ZCrafter backend is its MCP client, reaching it over Streamable HTTP. Bridge exposes each tool with an `approval: never|required` flag so backend knows which calls need a human's yes before backend ever invokes them — bridge itself doesn't gate anything; it executes what it's asked and logs the outcome. See [How approval works](#how-approval-works).

---

## Setup

### Before you start

- **Python 3.11+** and **Node.js 20+**
- Either a working **Zowe CLI profile** (local dev — test it with `zowe zosmf check status`) or a z/OSMF host/user/password to set directly as env vars (containers/KinD, e.g. against IBM Z Xplore). See [Configuration](#configuration).

### 1. Get the code

```bash
git clone https://github.com/ZcrafterAI/Bridge.git
cd Bridge
```

### 2. Install

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cd credential-resolver && npm install && npm run build && cd ..
```

By default the credential resolver reads your mainframe password from your OS keychain at run time. **No password is stored in this repo.** Running in a container instead? Skip the resolver build and set `MAINFRAME_WORKFLOW_CREDENTIAL_SOURCE=env` — see [Configuration](#configuration).

### 3. Check it starts

```bash
python -m mainframe_workflow_mcp.server
```

Bridge runs as an MCP server over **Streamable HTTP**, listening on `0.0.0.0:8000/mcp` by default (see [Configuration](#configuration) to change host/port/path). It's meant to be reached by the ZCrafter backend's MCP client, not spawned per-session by a coding assistant. Press `Ctrl+C` to stop it. Errors? See [Troubleshooting](#troubleshooting).

### 4. Point backend at it

Set backend's MCP server URL to `http://<bridge-host>:8000/mcp` (in-cluster service DNS name when running in KinD, `localhost` for local dev).

---

## How approval works

**Reading is free.** Every tool tagged `approval: "never"` — listing datasets, reading members, checking jobs, searching spool — runs immediately, no gate.

**Changing anything is backend's call.** Tools tagged `approval: "required"` — writing a member, submitting a job, deleting a dataset — still run immediately when bridge receives them; bridge trusts its caller. The actual human-in-the-loop gate lives in backend's approval-gate state, which gets a user's explicit yes (via a correlated pending-action REST POST) before it ever calls bridge for one of these. Call `zowe.capabilities.list` to see which tools require approval.

Every call, gated or not, is logged to bridge's local action log: tool, target, status, and a sanitized copy of the input (passwords redacted, diffs hashed, bulk content truncated) — never the full job/member content, and never an approval decision, since bridge doesn't make one.

---

## Tools

| | |
|---|---|
| **Datasets** | list, info, read, write, create, delete, rename, copy |
| **Members** | list, read, search, write, patch, delete, rename |
| **Jobs** | list, status, submit, cancel, purge, wait, JCL, spool |
| **Other** | verify connection, list profiles, search the tool catalog |

Large reads (`member.read`, `dataset.read`, `job.output`, `job.spool.read`) accept `searchText`, `maxLines` and `regex` — so the agent finds one line in a 40,000-line job log instead of pulling the whole thing into context.

---

## Configuration

Copy `.env.example` to `.env` to change defaults.

| Variable | Default | |
|---|---|---|
| `MAINFRAME_WORKFLOW_CREDENTIAL_SOURCE` | `resolver` | `resolver` (local Zowe profile + OS keychain) or `env` (below — containers/KinD) |
| `MAINFRAME_WORKFLOW_ZOWE_PROFILE` | `default` | Which Zowe profile to use (`resolver` source only) |
| `MAINFRAME_WORKFLOW_ZOSMF_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_PROTOCOL` / `_REJECT_UNAUTHORIZED` | — | Direct z/OSMF connection (`env` source only) — e.g. your IBM Z Xplore credentials |
| `MAINFRAME_WORKFLOW_DB_PATH` | `./mainframe_workflow_mcp/state.db` | Where the action log is stored |
| `MAINFRAME_WORKFLOW_APIML_BASE_PATH` | — | Set if z/OSMF is behind API ML |
| `MAINFRAME_WORKFLOW_MCP_TRANSPORT` | `http` | MCP transport (Streamable HTTP) |
| `MAINFRAME_WORKFLOW_MCP_HOST` | `0.0.0.0` | Bind host |
| `MAINFRAME_WORKFLOW_MCP_PORT` | `8000` | Bind port |
| `MAINFRAME_WORKFLOW_MCP_PATH` | `/mcp` | HTTP path backend's MCP client connects to |

---

## Troubleshooting

**`Zowe config not found`** — Bridge reads `~/.zowe/zowe.config.json`. Run `zowe config list` to confirm you have one.

**`z/OSMF profile "default" not found`** — your profile has another name. Run `zowe config list profiles`, then set `MAINFRAME_WORKFLOW_ZOWE_PROFILE` in `.env`.

**`Resolved profile is missing host/user/password`** — credentials aren't in your OS vault. Re-run `zowe config secure`.

**`CREDENTIAL_SOURCE=env requires ZOSMF_HOST, _USER and _PASSWORD`** — one of those three env vars is empty; there's no keychain fallback in `env` mode.

**Backend can't reach bridge** — confirm bridge is listening on the configured host/port (`curl -X POST http://<bridge-host>:8000/mcp ...`) and that backend's MCP server URL points at the same `/mcp` path.

---

## Running in a container

The image runs with `MAINFRAME_WORKFLOW_CREDENTIAL_SOURCE=env` (no Node/keytar — there's no OS keychain in a container), so pass your z/OSMF connection directly:

```bash
docker build -t zcrafter-bridge .
docker run -p 8000:8000 \
  -e MAINFRAME_WORKFLOW_ZOSMF_HOST=<xplore-host> \
  -e MAINFRAME_WORKFLOW_ZOSMF_USER=<user> \
  -e MAINFRAME_WORKFLOW_ZOSMF_PASSWORD=<password> \
  zcrafter-bridge
```

In KinD, those three come from a mounted K8s Secret instead of literal `-e` flags.

### A note on IBM Z Xplore

If your `ZOSMF_HOST` points at [IBM Z Xplore](https://ibm.com/z/resources/zxplore): it's a **shared, multi-tenant learning environment**, not a private sandbox. Treat credentials against it as rate-limited and best-effort:

- Don't wire it into automated CI or any repeated/scripted test loop. Manual runs only.
- `job.wait`'s polling is clamped server-side (max 60 attempts, minimum 1s apart) specifically so this tool can't hammer a shared z/OSMF instance with a tight loop, no matter what a caller asks for.
- If KinD's dev environment ends up exercising Xplore through automated test cycles rather than manual runs, stop and reconsider — that's the usage pattern the platform wasn't built for.

---

## Development

```bash
pip install -r requirements-dev.txt
pytest                                    # 47 tests
cd credential-resolver && npm test        # 8 tests
```

Architecture notes: [docs/architecture.md](docs/architecture.md). The z/OSMF calls live in `mainframe_workflow_mcp/toolbox/`; if the private `zcrafter-mainframe-mcp` package is installed, it's preferred automatically.

---

MIT licensed. Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
