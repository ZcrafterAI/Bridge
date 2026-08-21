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

Mutating z/OS tools stay blocked until a human has approved a written spec **and** a written plan in chat. That gate is instruction-based plus the MCP host’s own permission prompts. It is not a cryptographic proof that a human clicked “approve.”
