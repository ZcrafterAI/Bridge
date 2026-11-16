# Security

## Credentials

This project never stores mainframe passwords in the repo. Host, user, and password come from your existing Zowe profile in the OS credential vault (via `credential-resolver`). Do not paste vault secrets, `.env` values, or `zowe.config.json` into issues or pull requests.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for a security problem. Email the maintainer listed on the GitHub profile, or use GitHub’s private vulnerability reporting if it is enabled on this repository.

Include:

- What the issue is
- How to reproduce it
- Whether any credentials or mainframe data were exposed

## What this server will not do

Mutating z/OS tools stay blocked until a person has approved a written spec **and** a written plan, and then only the changes that plan lists can run.

The agent cannot approve for the person. `approve_spec` and `approve_plan` make the server ask the person directly: in the AI client's own prompt, on a page the server opens on `127.0.0.1` whose one-time token is never sent to the agent, or in a terminal. See [docs/architecture.md](docs/architecture.md#approval).

Limits you should know:

- An agent with a shell on the same machine as the server is outside this gate. It could read the server's store or log, or call z/OSMF with its own tools. Give such an agent only the MCP connection, or run Bridge on another machine.
- A step that leaves content open (the approval says so) lets the agent choose that content. Ask for the exact content in the plan when it matters.
- `MAINFRAME_WORKFLOW_APPROVAL=unsafe-agent` removes the person entirely. It is for automated runs against throwaway systems.
- Bridge acts with your Zowe profile's z/OS permissions. It cannot do what your user ID cannot do, and it does not narrow them unless you set `MAINFRAME_WORKFLOW_READ_ONLY` or `MAINFRAME_WORKFLOW_PROTECTED_DATASETS`.
