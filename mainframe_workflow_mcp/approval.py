"""Getting a person's yes.

An agent can ask for an approval; it can never give one. The answer comes from a channel
the agent does not control:

  * the AI client's own prompt (MCP elicitation), when the client has one. On protocol
    versions before 2026-07-28 the server asks during the call; from 2026-07-28 the call
    returns "input required" and the client retries it with the person's answer. Or
  * a page this server opens in the person's browser, on this machine only, or
  * `zcrafter-bridge approve` in a terminal, for machines with no browser.

The page's address carries a one-time token that is never sent to the agent, so an agent that
can fetch web pages still cannot press Approve.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import http.server
import json
import secrets
import sys
import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .db import RequestStore
from .plan_steps import CONTENT_KEYS, describe_steps, step_target

MODES = ("auto", "prompt", "browser", "terminal", "unsafe-agent")
_SHOWN_CHARS = 6000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Decision:
    status: str  # "approved" | "rejected" | "waiting" | "ask-client"
    via: str = ""
    detail: str = ""
    # For "ask-client": what the tool must return so the client asks the person and retries.
    payload: Any = None


_CHOICES = ["Approve", "Reject"]
_PROMPT_KEY = "approval"
_PROMPT_SCHEMA = {
    "type": "object",
    # The same shape FastMCP gives a list of choices on older protocol versions.
    "properties": {"value": {"type": "string", "enum": _CHOICES, "title": "Decision"}},
    "required": ["value"],
}


def _client_can_prompt(ctx: Any) -> bool:
    try:
        return getattr(ctx.session.client_capabilities, "elicitation", None) is not None
    except Exception:
        return False


def _retries_with_answers(ctx: Any) -> bool:
    """True from protocol 2026-07-28, where a server can no longer ask during a call."""
    try:
        return str(ctx.request_context.protocol_version) >= "2026-07-28"
    except Exception:
        return False


def approval_subject(store: RequestStore, request_id: str, kind: str, version: int) -> dict[str, Any]:
    """What the person is asked to approve, read from the store at that version."""
    request = store.get_request(request_id) or {}
    if kind == "spec":
        revision = store.latest_spec_revision(request_id) or {}
        steps: list[dict[str, Any]] = []
    else:
        revision = store.get_plan_revision(request_id, version) or {}
        steps = json.loads(revision["steps_json"]) if revision.get("steps_json") else []
    return {
        "request_id": request_id,
        "kind": kind,
        "version": version,
        "raw_request": request.get("raw_request", ""),
        "content": revision.get("content", "") if revision.get("version") == version else "",
        "steps": steps,
    }


def approval_text(subject: dict[str, Any]) -> str:
    """The approval as plain text, for a client prompt or a terminal."""
    kind = subject["kind"]
    lines = [
        f"Approve this {kind} for the mainframe request?",
        "",
        f"Request: {subject['raw_request']}",
        "",
        f"{kind.capitalize()} (version {subject['version']}):",
        subject["content"][:_SHOWN_CHARS],
    ]
    if kind == "plan":
        lines += [
            "",
            "Changes this plan allows, and nothing else:",
            describe_steps(subject["steps"]),
        ]
    else:
        lines += ["", "Approving the spec changes nothing yet. The plan is approved separately."]
    return "\n".join(lines)


class ApprovalBroker:
    def __init__(
        self,
        store: RequestStore,
        *,
        mode: str = "auto",
        wait_seconds: float = 60.0,
        open_browser: Callable[[str], Any] | None = None,
        log: Callable[[str], None] | None = None,
        poll_seconds: float = 0.4,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"Unknown approval mode {mode!r}; use one of {', '.join(MODES)}.")
        self.store = store
        self.mode = mode
        self.wait_seconds = wait_seconds
        # Looked up at call time, so a test (or an embedder) can replace webbrowser.open.
        self._open_browser = open_browser or (lambda url: webbrowser.open(url))
        self._log = log or (lambda line: print(line, file=sys.stderr, flush=True))
        self._poll_seconds = poll_seconds
        self._tokens: dict[str, str] = {}  # approval id -> token; never leaves this process
        self._opened: set[str] = set()
        self._server: http.server.ThreadingHTTPServer | None = None
        self._lock = threading.Lock()

    # ---- the one entry point ----

    async def ask(self, ctx: Any, request_id: str, kind: str, version: int) -> Decision:
        if self.mode == "unsafe-agent":
            return Decision("approved", "unsafe-agent (nobody was asked)")

        # An answer the person already gave for this exact version stands.
        existing = self.store.find_approval(request_id, kind, version)
        if existing and existing["status"] == "APPROVED":
            return Decision("approved", existing.get("via") or "")
        if existing and existing["status"] == "REJECTED":
            return Decision("rejected", existing.get("via") or "")

        subject = approval_subject(self.store, request_id, kind, version)
        # Once the person has been sent to the page or the terminal, wait for them there.
        waiting_elsewhere = bool(existing and existing["status"] == "PENDING")
        if self.mode in ("auto", "prompt") and not waiting_elsewhere:
            decision = await self._ask_client(ctx, subject)
            if decision is not None:
                return decision
            if self.mode == "prompt":
                return Decision(
                    "waiting",
                    detail="This AI client did not show an approval prompt. Set "
                    "MAINFRAME_WORKFLOW_APPROVAL=auto to approve in the browser instead.",
                )
        return await self._ask_out_of_band(subject, existing, open_page=self.mode in ("auto", "browser"))

    # ---- the AI client's own prompt ----

    async def _ask_client(self, ctx: Any, subject: dict[str, Any]) -> Decision | None:
        """A decision from the client's prompt, or None when it cannot ask."""
        if ctx is None or not _client_can_prompt(ctx):
            return None
        text = approval_text(subject)
        if _retries_with_answers(ctx):
            state = f"{subject['request_id']}|{subject['kind']}|{subject['version']}"
            responses = getattr(ctx, "input_responses", None)
            # An answer counts only for the exact revision it was asked about.
            if responses and _PROMPT_KEY in responses and getattr(ctx, "request_state", None) == state:
                answer = responses[_PROMPT_KEY]
                content = getattr(answer, "content", None) or {}
                return self._from_client(subject, getattr(answer, "action", None), content.get("value"))
            try:
                import mcp_types
            except ImportError:  # an MCP library from before this protocol version
                return None
            return Decision("ask-client", payload=mcp_types.InputRequiredResult(
                input_requests={_PROMPT_KEY: mcp_types.ElicitRequest(
                    params=mcp_types.ElicitRequestFormParams(message=text, requested_schema=_PROMPT_SCHEMA),
                )},
                request_state=state,
            ))
        try:
            result = await ctx.elicit(text, _CHOICES)
        except Exception:  # the client has no prompt of its own after all
            return None
        return self._from_client(subject, getattr(result, "action", None), getattr(result, "data", None))

    def _from_client(self, subject: dict[str, Any], action: Any, choice: Any) -> Decision | None:
        via = "the AI client's prompt"
        if action == "accept" and choice == "Approve":
            self._record(subject, "APPROVED", via)
            return Decision("approved", via)
        if action == "decline" or (action == "accept" and choice == "Reject"):
            self._record(subject, "REJECTED", via)
            return Decision("rejected", via)
        # Dismissed without an answer: ask another way rather than guess.
        return None

    def _record(self, subject: dict[str, Any], status: str, via: str) -> None:
        approval_id = str(uuid4())
        now = _now()
        self.store.create_approval(
            approval_id, subject["request_id"], subject["kind"], subject["version"],
            _hash(secrets.token_urlsafe(24)), now=now,
        )
        self.store.decide_approval(approval_id, status, via, now=now)

    # ---- the browser page and the terminal ----

    async def _ask_out_of_band(
        self, subject: dict[str, Any], existing: dict | None, *, open_page: bool,
    ) -> Decision:
        approval_id = existing["id"] if existing and existing["status"] == "PENDING" else None
        if approval_id is None or (open_page and approval_id not in self._tokens):
            # A pending approval from an earlier run has a token this process never knew.
            if approval_id is not None:
                self.store.decide_approval(approval_id, "EXPIRED", "superseded", now=_now())
            approval_id = str(uuid4())
            token = secrets.token_urlsafe(24)
            self._tokens[approval_id] = token
            self.store.create_approval(
                approval_id, subject["request_id"], subject["kind"], subject["version"],
                _hash(token), now=_now(),
            )
        if open_page:
            url = self.page_url(approval_id)
            self._log(f"[bridge] Approval needed for the {subject['kind']}: {url}")
            if approval_id not in self._opened:
                self._opened.add(approval_id)
                try:
                    shown = self._open_browser(url)
                except Exception as exc:
                    shown = False
                    self._log(f"[bridge] Could not open a browser ({exc}).")
                if shown is False:
                    self._log(
                        "[bridge] No browser opened. Open the address above, or run "
                        "`zcrafter-bridge approve` in a terminal."
                    )
        else:
            self._log(
                f"[bridge] Approval needed for the {subject['kind']}: run "
                "`zcrafter-bridge approve` in a terminal."
            )

        deadline = asyncio.get_running_loop().time() + self.wait_seconds
        while True:
            row = self.store.get_approval(approval_id)
            if row and row["status"] == "APPROVED":
                return Decision("approved", row.get("via") or "")
            if row and row["status"] == "REJECTED":
                return Decision("rejected", row.get("via") or "")
            if asyncio.get_running_loop().time() >= deadline:
                terminal = "by running `zcrafter-bridge approve` in a terminal"
                where = f"on the page Bridge opened in their browser, or {terminal}" if open_page else terminal
                return Decision("waiting", detail=f"The person has not answered yet. They approve {where}.")
            await asyncio.sleep(self._poll_seconds)

    def page_url(self, approval_id: str) -> str:
        port = self._ensure_server()
        return f"http://127.0.0.1:{port}/approval/{approval_id}?t={self._tokens[approval_id]}"

    def _ensure_server(self) -> int:
        with self._lock:
            if self._server is None:
                handler = _make_handler(self.store)
                self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
                threading.Thread(target=self._server.serve_forever, daemon=True).start()
            return self._server.server_address[1]

    def close(self) -> None:
        with self._lock:
            if self._server is not None:
                self._server.shutdown()
                self._server.server_close()
                self._server = None


# ---------------------------------------------------------------- the page

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; --ink: #151412; --muted: #5f5c57; --line: #d6d3ce; --bg: #fafaf9; --box: #f1f0ee; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --ink: #ecebe8; --muted: #a09d98; --line: #3d3b38; --bg: #151412; --box: #1f1e1c; }} }}
  body {{ margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, sans-serif; }}
  main {{ max-width: 760px; margin: 0 auto; padding: 40px 20px 64px; }}
  h1 {{ font-size: 26px; line-height: 1.2; margin: 0 0 8px; font-weight: 600; }}
  h2 {{ font-size: 15px; margin: 32px 0 8px; color: var(--muted); font-weight: 600; }}
  p {{ margin: 0 0 12px; }}
  pre {{ margin: 0; padding: 14px 16px; background: var(--box); border: 1px solid var(--line); border-radius: 4px; overflow-x: auto; white-space: pre-wrap; word-break: break-word; font: 13px/1.5 ui-monospace, Menlo, monospace; }}
  ol {{ margin: 0; padding: 0; list-style: none; }}
  li {{ padding: 14px 0; border-top: 1px solid var(--line); }}
  li:last-child {{ border-bottom: 1px solid var(--line); }}
  .tool {{ font: 600 14px ui-monospace, Menlo, monospace; }}
  .target {{ font: 14px ui-monospace, Menlo, monospace; word-break: break-all; }}
  .note {{ color: var(--muted); font-size: 14px; margin-top: 4px; }}
  .warn {{ font-weight: 600; }}
  form {{ display: flex; gap: 12px; margin-top: 32px; flex-wrap: wrap; }}
  button {{ font: inherit; font-weight: 600; padding: 10px 20px; border-radius: 4px; border: 1px solid var(--ink); background: var(--ink); color: var(--bg); cursor: pointer; }}
  button.reject {{ background: transparent; color: var(--ink); }}
  .muted {{ color: var(--muted); }}
</style></head><body><main>{body}</main></body></html>"""


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _clip(text: str) -> str:
    if len(text) <= _SHOWN_CHARS:
        return text
    return f"{text[:_SHOWN_CHARS]}\n... ({len(text)} characters in all)"


def _step_html(step: dict[str, Any], index: int) -> str:
    args = step.get("args") or {}
    parts = [
        f'<div><span class="tool">{index}. {_esc(step["tool"])}</span> '
        f'<span class="target">{_esc(step_target(step))}</span></div>'
    ]
    times = int(step.get("times") or 1)
    if times > 1:
        parts.append(f'<div class="note">May run up to {times} times.</div>')
    shown = False
    for key in sorted(CONTENT_KEYS):
        if key in args:
            value = args[key] if isinstance(args[key], str) else json.dumps(args[key], indent=2)
            parts.append(f'<div class="note">{_esc(key)}, exactly as it will be sent:</div><pre>{_esc(_clip(value))}</pre>')
            shown = True
    if step["tool"] == "job.submit" and "jcl" not in args:
        parts.append('<div class="note warn">Runs the JCL in that dataset as it stands when the job is submitted.</div>')
    elif not shown and step["tool"] in {"dataset.write", "member.write", "member.patch", "uss.write"}:
        parts.append('<div class="note warn">The exact content is not fixed by this plan.</div>')
    for key, value in sorted(args.items()):
        if key in CONTENT_KEYS or key in {
            "dataset", "member", "sourceDataset", "sourceMember", "targetDataset", "targetMember",
            "newDataset", "newMember", "path", "newPath", "command", "jobId",
        }:
            continue
        parts.append(f'<div class="note">{_esc(key)}: {_esc(value)}</div>')
    return "<li>" + "".join(parts) + "</li>"


def render_page(subject: dict[str, Any], approval_id: str, token: str) -> str:
    kind = subject["kind"]
    body = [
        f"<h1>Approve this {_esc(kind)}?</h1>",
        '<p class="muted">Zcrafter Bridge is asking on behalf of an AI agent. Nothing changes on the '
        "mainframe unless you approve.</p>",
        "<h2>What was asked</h2>", f"<pre>{_esc(_clip(subject['raw_request']))}</pre>",
        f"<h2>The {_esc(kind)} (version {subject['version']})</h2>",
        f"<pre>{_esc(_clip(subject['content']))}</pre>",
    ]
    if kind == "plan":
        body.append("<h2>Changes this plan allows, and nothing else</h2>")
        if subject["steps"]:
            body.append("<ol>" + "".join(_step_html(s, i) for i, s in enumerate(subject["steps"], 1)) + "</ol>")
        else:
            body.append("<p>No changes are listed, so this plan cannot change anything.</p>")
    else:
        body.append('<p class="muted" style="margin-top:16px">Approving the spec changes nothing yet. '
                    "The plan is approved separately.</p>")
    body.append(
        f'<form method="post" action="/approval/{_esc(approval_id)}">'
        f'<input type="hidden" name="t" value="{_esc(token)}">'
        '<button name="decision" value="approve">Approve</button>'
        '<button class="reject" name="decision" value="reject">Reject</button></form>'
    )
    return _PAGE.format(title=f"Approve this {_esc(kind)}?", body="".join(body))


def _message_page(title: str, text: str) -> str:
    return _PAGE.format(title=_esc(title), body=f"<h1>{_esc(title)}</h1><p>{_esc(text)}</p>")


def _make_handler(store: RequestStore) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:  # stay quiet on the MCP channel
            return

        def _send(self, code: int, page: str) -> None:
            body = page.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def _local(self) -> bool:
            """Only this machine's own address may be used to reach the page."""
            host = (self.headers.get("Host") or "").split(":")[0].lower()
            return host in {"127.0.0.1", "localhost"}

        def _approval(self, token: str) -> dict | None:
            path = urlparse(self.path).path
            if not path.startswith("/approval/"):
                return None
            row = store.get_approval(path[len("/approval/"):])
            if row is None or not token or not hmac.compare_digest(_hash(token), row["token_hash"]):
                return None
            return row

        def do_GET(self) -> None:
            if not self._local():
                return self._send(403, _message_page("Not allowed", "Open this page from this machine."))
            token = (parse_qs(urlparse(self.path).query).get("t") or [""])[0]
            row = self._approval(token)
            if row is None:
                return self._send(404, _message_page("Not found", "This approval link is not valid."))
            if row["status"] != "PENDING":
                return self._send(200, _message_page("Already answered", f"This {row['kind']} was {row['status'].lower()}."))
            subject = approval_subject(store, row["request_id"], row["kind"], row["version"])
            self._send(200, render_page(subject, row["id"], token))

        def do_POST(self) -> None:
            if not self._local():
                return self._send(403, _message_page("Not allowed", "Open this page from this machine."))
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).hostname not in {"127.0.0.1", "localhost"}:
                return self._send(403, _message_page("Not allowed", "This answer came from another site."))
            length = min(int(self.headers.get("Content-Length") or 0), 16_384)
            form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            row = self._approval((form.get("t") or [""])[0])
            if row is None:
                return self._send(404, _message_page("Not found", "This approval link is not valid."))
            choice = (form.get("decision") or [""])[0]
            if choice not in {"approve", "reject"}:
                return self._send(400, _message_page("Not understood", "Choose Approve or Reject."))
            status = "APPROVED" if choice == "approve" else "REJECTED"
            if not store.decide_approval(row["id"], status, "the approval page", now=_now()):
                return self._send(200, _message_page("Already answered", "This was answered before."))
            done = "Approved" if status == "APPROVED" else "Rejected"
            self._send(200, _message_page(done, "You can close this tab and go back to your AI client."))

    return Handler
