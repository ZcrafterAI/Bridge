from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4
from .db import RequestStore
from ._toolbox import list_tool_definitions
from .plan_steps import remaining_steps, validate_steps as _check_steps


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_view(plan: dict | None) -> dict | None:
    """A plan revision as callers see it: its steps as a list, not stored JSON."""
    if plan is None:
        return None
    view = {k: v for k, v in plan.items() if k != "steps_json"}
    view["steps"] = json.loads(plan["steps_json"]) if plan.get("steps_json") else []
    return view


class RequestManager:
    def __init__(
        self,
        store: RequestStore,
        validate_steps: Callable[[Any], list[dict[str, Any]]] | None = None,
        protected: list[str] | None = None,
    ):
        self.store = store
        # Checks a plan's steps against the tool catalog and the protected datasets.
        self._validate_steps = validate_steps or (
            lambda steps: _check_steps(steps, list_tool_definitions(), protected or [])
        )

    def _require_active(self, request_id: str) -> dict:
        request = self.store.get_request(request_id)
        if request is None:
            raise ValueError(f"No such request: {request_id}")
        if request["status"] != "ACTIVE":
            raise ValueError(f"Request {request_id} is {request['status']}, not ACTIVE")
        return request

    def get_request(self, request_id: str) -> dict | None:
        return self.store.get_request(request_id)

    def start_request(self, raw_request: str) -> dict:
        request_id = str(uuid4())
        self.store.create_request(request_id, raw_request, now=_now())
        return {"request_id": request_id, "phase": "CLARIFYING", "status": "ACTIVE"}

    def record_clarification(self, request_id: str, question: str, answer: str) -> dict:
        self._require_active(request_id)
        now = _now()
        self.store.add_clarification(request_id, question, answer, now=now)
        self.store.update_phase_status(request_id, now=now)
        return {"ok": True}

    def get_request_status(self, request_id: str) -> dict:
        request = self.store.get_request(request_id)
        if request is None:
            raise ValueError(f"No such request: {request_id}")
        spec = self.store.latest_spec_revision(request_id)
        plan = _plan_view(self.store.latest_plan_revision(request_id))
        approved = self.approved_plan(request_id)
        return {
            **request,
            "clarifications": [
                {"question": c["question"], "answer": c["answer"]}
                for c in self.store.list_clarifications(request_id)
            ],
            "latest_spec": spec,
            "latest_plan": plan,
            "steps_remaining": remaining_steps(approved[1], approved[2]) if approved else [],
            "recent_actions": self.store.list_action_log(request_id),
        }

    def approved_plan(self, request_id: str) -> tuple[int, list[dict[str, Any]], dict[int, int]] | None:
        """(version, steps, uses per step) of the plan a person approved, or None."""
        request = self.store.get_request(request_id)
        if request is None or request["plan_approved_version"] is None:
            return None
        version = int(request["plan_approved_version"])
        revision = self.store.get_plan_revision(request_id, version)
        if revision is None:
            return None
        steps = json.loads(revision["steps_json"]) if revision.get("steps_json") else []
        return version, steps, self.store.step_uses(request_id, version)

    def record_step_use(self, request_id: str, plan_version: int, step_index: int) -> None:
        self.store.add_step_use(request_id, plan_version, step_index, now=_now())

    def list_requests(self, status: str = "ACTIVE") -> list[dict]:
        return self.store.list_requests(status)

    _RESET_ON_SPEC_EDIT = {"SPEC_APPROVED", "PLAN_DRAFT", "PLAN_APPROVED", "EXECUTING"}

    def draft_spec(self, request_id: str, content: str) -> dict:
        request = self._require_active(request_id)
        latest = self.store.latest_spec_revision(request_id)
        version = (latest["version"] if latest else 0) + 1
        now = _now()
        self.store.add_spec_revision(request_id, version, content, now=now)

        if request["phase"] in self._RESET_ON_SPEC_EDIT:
            # An approved plan was written against a specific approved spec.
            # If the spec changes after approval, that plan's assumptions may
            # no longer hold, so both approvals are cleared, not just the spec's.
            self.store.update_phase_status(
                request_id, phase="SPEC_DRAFT",
                clear_spec_approval=True, clear_plan_approval=True, now=now,
            )
        else:
            self.store.update_phase_status(request_id, phase="SPEC_DRAFT", now=now)

        return {"request_id": request_id, "phase": "SPEC_DRAFT", "version": version}

    def revision_awaiting_approval(self, request_id: str, kind: str) -> dict:
        """The spec or plan revision a person is about to be asked about."""
        request = self._require_active(request_id)
        wanted = "SPEC_DRAFT" if kind == "spec" else "PLAN_DRAFT"
        if request["phase"] != wanted:
            raise ValueError(
                f"Cannot approve {kind} for {request_id}: phase must be {wanted}, is {request['phase']}"
            )
        if kind == "spec":
            return self.store.latest_spec_revision(request_id)
        return self.store.latest_plan_revision(request_id)

    def approve_spec(self, request_id: str, *, version: int | None = None) -> dict:
        """Record that a person approved the spec. Never exposed to the agent directly:
        the server calls this only after its approval step returned a person's yes.
        `version` is the revision the person saw; a spec edited since then is not approved."""
        request = self._require_active(request_id)
        if request["phase"] != "SPEC_DRAFT":
            raise ValueError(
                f"Cannot approve spec for {request_id}: phase must be SPEC_DRAFT, is {request['phase']}"
            )
        latest = self.store.latest_spec_revision(request_id)
        if version is not None and latest["version"] != version:
            raise ValueError(
                f"The spec for {request_id} changed after approval was asked "
                f"(asked on version {version}, now {latest['version']}); ask again."
            )
        now = _now()
        self.store.update_phase_status(
            request_id, phase="SPEC_APPROVED",
            spec_approved_version=latest["version"], spec_approved_at=now, now=now,
        )
        return {"request_id": request_id, "phase": "SPEC_APPROVED", "approved_version": latest["version"]}

    _PLAN_DRAFTABLE_PHASES = {"SPEC_APPROVED", "PLAN_DRAFT", "PLAN_APPROVED", "EXECUTING"}
    _RESET_ON_PLAN_EDIT = {"PLAN_APPROVED", "EXECUTING"}

    def draft_plan(self, request_id: str, content: str, steps: Any = None) -> dict:
        request = self._require_active(request_id)
        if request["phase"] not in self._PLAN_DRAFTABLE_PHASES:
            raise ValueError(
                f"Cannot draft a plan for {request_id}: spec must be approved first "
                f"(current phase={request['phase']})"
            )
        # Steps are checked before anything is stored, so a bad plan leaves no revision.
        checked = self._validate_steps(steps)
        latest = self.store.latest_plan_revision(request_id)
        version = (latest["version"] if latest else 0) + 1
        now = _now()
        self.store.add_plan_revision(
            request_id, version, content, now=now,
            steps_json=json.dumps(checked) if checked else None,
        )

        if request["phase"] in self._RESET_ON_PLAN_EDIT:
            self.store.update_phase_status(
                request_id, phase="PLAN_DRAFT", clear_plan_approval=True, now=now,
            )
        else:
            self.store.update_phase_status(request_id, phase="PLAN_DRAFT", now=now)

        return {"request_id": request_id, "phase": "PLAN_DRAFT", "version": version, "steps": len(checked)}

    def approve_plan(self, request_id: str, *, version: int | None = None) -> dict:
        """Record that a person approved the plan. See approve_spec."""
        request = self._require_active(request_id)
        if request["phase"] != "PLAN_DRAFT":
            raise ValueError(
                f"Cannot approve plan for {request_id}: phase must be PLAN_DRAFT, is {request['phase']}"
            )
        latest = self.store.latest_plan_revision(request_id)
        if version is not None and latest["version"] != version:
            raise ValueError(
                f"The plan for {request_id} changed after approval was asked "
                f"(asked on version {version}, now {latest['version']}); ask again."
            )
        now = _now()
        self.store.update_phase_status(
            request_id, phase="PLAN_APPROVED",
            plan_approved_version=latest["version"], plan_approved_at=now, now=now,
        )
        return {"request_id": request_id, "phase": "PLAN_APPROVED", "approved_version": latest["version"]}

    def mark_executing(self, request_id: str) -> None:
        request = self._require_active(request_id)
        if request["phase"] == "EXECUTING":
            # Idempotent: already executing, nothing to do
            return
        if request["phase"] != "PLAN_APPROVED":
            raise ValueError(
                f"Cannot mark {request_id} as executing: phase must be PLAN_APPROVED, is {request['phase']}"
            )
        self.store.update_phase_status(request_id, phase="EXECUTING", now=_now())

    def cancel_request(self, request_id: str, reason: str) -> dict:
        self._require_active(request_id)
        self.store.update_phase_status(request_id, status="ABANDONED", cancel_reason=reason, now=_now())
        return {"request_id": request_id, "status": "ABANDONED"}

    def complete_request(self, request_id: str) -> dict:
        request = self._require_active(request_id)
        if request["phase"] not in ("PLAN_APPROVED", "EXECUTING"):
            raise ValueError(
                f"Cannot complete {request_id}: plan must be PLAN_APPROVED or EXECUTING, "
                f"is {request['phase']}"
            )
        self.store.update_phase_status(request_id, status="COMPLETED", now=_now())
        return {"request_id": request_id, "status": "COMPLETED"}
