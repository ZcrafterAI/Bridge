# Zcrafter Bridge

Give Claude Code real access to your mainframe — and keep it from changing anything you haven't approved.

Ask in plain English: *"Why did PAYJOB fail?"* Claude reads the spool, finds the cause, tells you. Ask it to **fix** something and it stops: it writes a spec, waits for your yes, writes a plan, waits again. Only then does it touch z/OS.

```
You:     The batch job PAYJOB is failing. Find out why and fix it.
Claude:  [reads the spool, finds a missing dataset]
         Here's the spec — one line of JCL to change. Approve?
You:     yes
Claude:  Here's the plan. Approve?
You:     yes
Claude:  Patched, resubmitted, CC 0000. Done.
```

---

## What's an MCP server?

MCP is how Claude Code talks to outside systems. An MCP server hands Claude a set of tools it can call. Bridge is an MCP server whose tools are your mainframe — datasets, members, jobs, spool — with an approval gate in front of anything destructive.

Install it once, point Claude Code at it, then just talk to Claude.

---

## Setup

### Before you start

- **Python 3.11+** and **Node.js 20+**
- **Claude Code** — [install guide](https://docs.claude.com/en/docs/claude-code)
- A working **Zowe CLI profile**. Test it: `zowe zosmf check status`. If that fails, fix Zowe first — Bridge reads the same profile.

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

The credential resolver reads your mainframe password from your OS keychain at run time. **No password is stored in this repo.**

### 3. Check it starts

```bash
python -m mainframe_workflow_mcp.server
```

It should start and wait silently. Press `Ctrl+C`. Errors? See [Troubleshooting](#troubleshooting).

### 4. Connect Claude Code

From inside the `Bridge` folder:

```bash
claude mcp add mainframe-workflow -- "$(pwd)/.venv/bin/python" -m mainframe_workflow_mcp.server
```

Windows: use `.venv\Scripts\python.exe`.

Verify with `claude mcp list` — you want `mainframe-workflow: ✔ Connected`.

### 5. Install the skill

```bash
mkdir -p ~/.claude/skills
cp -r .claude/skills/mainframe-workflow ~/.claude/skills/
```

This teaches Claude the approval workflow. Without it, Claude has the tools but not the process.

### 6. Try it

Start `claude` and ask:

```
What datasets do I have?
```

Then something real:

```
Why did my last failed job fail?
```

---

## How the gate works

**Reading is free.** Listing datasets, reading members, checking jobs, searching spool — no approval needed.

**Changing anything is gated.** Before Claude can write a member, submit a job, or delete a dataset, it must:

1. Open a request
2. Write a **spec** — what changes and why — and get your explicit yes
3. Write a **plan** — the exact steps — and get your explicit yes

Editing the spec after approval un-approves the plan too. Every mutation is logged with its inputs; passwords are redacted, diffs are hashed.

An agent that skips a step gets `PLAN_NOT_APPROVED` instead of access to your system.

---

## Tools

| | |
|---|---|
| **Datasets** | list, info, read, write, create, delete, rename, copy |
| **Members** | list, read, search, write, patch, delete, rename |
| **Jobs** | list, status, submit, cancel, purge, wait, JCL, spool |
| **Other** | verify connection, list profiles, search the tool catalog |

Large reads (`member.read`, `dataset.read`, `job.output`, `job.spool.read`) accept `searchText`, `maxLines` and `regex` — so Claude finds one line in a 40,000-line job log instead of pulling the whole thing into context.

---

## Configuration

Copy `.env.example` to `.env` to change defaults.

| Variable | Default | |
|---|---|---|
| `MAINFRAME_WORKFLOW_ZOWE_PROFILE` | `default` | Which Zowe profile to use |
| `MAINFRAME_WORKFLOW_DB_PATH` | `./mainframe_workflow_mcp/state.db` | Where requests are stored |
| `MAINFRAME_WORKFLOW_IDLE_DAYS` | `14` | Abandon untouched requests after |
| `MAINFRAME_WORKFLOW_RETENTION_DAYS` | `90` | Archive finished requests after |
| `MAINFRAME_WORKFLOW_APIML_BASE_PATH` | — | Set if z/OSMF is behind API ML |

---

## Troubleshooting

**`Zowe config not found`** — Bridge reads `~/.zowe/zowe.config.json`. Run `zowe config list` to confirm you have one.

**`z/OSMF profile "default" not found`** — your profile has another name. Run `zowe config list profiles`, then set `MAINFRAME_WORKFLOW_ZOWE_PROFILE` in `.env`.

**`Resolved profile is missing host/user/password`** — credentials aren't in your OS vault. Re-run `zowe config secure`.

**Claude says a tool isn't allowed** — approve it when prompted, or check `claude mcp list`.

---

## Development

```bash
pip install -r requirements-dev.txt
pytest                                    # 87 tests
cd credential-resolver && npm test        # 8 tests
```

Architecture notes: [docs/architecture.md](docs/architecture.md). The z/OSMF calls live in `mainframe_workflow_mcp/toolbox/`; if the private `zcrafter-mainframe-mcp` package is installed, it's preferred automatically.

---

MIT licensed. Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
