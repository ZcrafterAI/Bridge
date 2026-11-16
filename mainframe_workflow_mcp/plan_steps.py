"""The steps of a plan: what a person approves, and what a change is checked against.

A plan used to be free text, so an approved plan unlocked every mutating tool for the
request. A plan now lists its changes as steps, each naming one tool and its target, and a
mutating call runs only when it matches a step that still has a use left.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Bulk arguments. A step may leave these out when the exact text is not known yet; the
# approval then says so. When a step does give one, the call must send exactly that.
CONTENT_KEYS = frozenset({"content", "unifiedDiff", "jcl", "attributes"})

# Names z/OS treats as case-insensitive.
_NAME_KEYS = frozenset({
    "dataset", "member", "newDataset", "newMember", "sourceDataset", "targetDataset",
    "sourceMember", "targetMember", "likeDataset", "jobId", "jobName", "jobClass",
    "consoleName",
})

# Arguments that say which dataset a call writes to, for the protected list.
_WRITE_TARGET_KEYS = ("dataset", "newDataset", "targetDataset")

# A call never has to repeat these in a step.
_IGNORED_KEYS = frozenset({"profileName", "request_id"})

MAX_STEPS = 50
MAX_TIMES = 20


class PlanStepError(ValueError):
    """A plan's steps are not valid. The message is written for the agent to act on."""


def _definitions_by_name(definitions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {d["name"]: d for d in definitions}


def identity_keys(definition: dict[str, Any]) -> list[str]:
    """The arguments a step must name: everything required that is not bulk content."""
    required = definition.get("inputSchema", {}).get("required", [])
    return [k for k in required if k not in CONTENT_KEYS and k not in _IGNORED_KEYS]


def _norm(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if key in _NAME_KEYS:
        return str(value).strip().upper()
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, (int, float)):
        return value
    return str(value).strip() if key == "command" else str(value)


def protected_pattern(patterns: list[str], dataset: str) -> str | None:
    """The first protected pattern a dataset name matches, or None."""
    name = dataset.strip().upper().strip("'")
    for pattern in patterns:
        if _pattern_regex(pattern).match(name):
            return pattern
    return None


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    out = ""
    text = pattern.strip().upper()
    i = 0
    while i < len(text):
        if text.startswith("**", i):
            out += ".*"
            i += 2
        elif text[i] == "*":
            out += "[^.]*"
            i += 1
        else:
            out += re.escape(text[i])
            i += 1
    return re.compile(f"^{out}$")


def protected_target(patterns: list[str], args: dict[str, Any]) -> tuple[str, str] | None:
    """(dataset, pattern) when a call would write to a protected dataset."""
    if not patterns:
        return None
    for key in _WRITE_TARGET_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            pattern = protected_pattern(patterns, value)
            if pattern:
                return value.strip().upper(), pattern
    return None


def validate_steps(
    steps: Any, definitions: list[dict[str, Any]], protected: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Check a plan's steps and return them in stored form. Raises PlanStepError."""
    if steps is None:
        return []
    if not isinstance(steps, list):
        raise PlanStepError("steps must be a list of {tool, args} objects.")
    if len(steps) > MAX_STEPS:
        raise PlanStepError(f"A plan holds at most {MAX_STEPS} steps; split the work into requests.")
    by_name = _definitions_by_name(definitions)
    cleaned: list[dict[str, Any]] = []
    for index, raw in enumerate(steps, start=1):
        if not isinstance(raw, dict):
            raise PlanStepError(f"Step {index} must be an object with tool and args.")
        tool = str(raw.get("tool") or "").strip()
        definition = by_name.get(tool)
        if definition is None:
            raise PlanStepError(f"Step {index}: no such tool {tool!r}.")
        if definition.get("approval") != "required":
            raise PlanStepError(
                f"Step {index}: {tool} only reads, so it needs no step. List only the changes."
            )
        args = raw.get("args") or {}
        if not isinstance(args, dict):
            raise PlanStepError(f"Step {index}: args must be an object.")
        properties = definition.get("inputSchema", {}).get("properties", {})
        args = {k: v for k, v in args.items() if k not in _IGNORED_KEYS and v is not None}
        unknown = sorted(k for k in args if k not in properties)
        if unknown:
            raise PlanStepError(f"Step {index}: {tool} has no argument {', '.join(unknown)}.")
        missing = [k for k in identity_keys(definition) if not str(args.get(k) or "").strip()]
        if missing:
            raise PlanStepError(
                f"Step {index}: {tool} must name {', '.join(missing)} so the person can see "
                "what will change."
            )
        if tool == "job.submit" and not (
            str(args.get("jcl") or "").strip() or str(args.get("dataset") or "").strip()
        ):
            raise PlanStepError(
                f"Step {index}: job.submit must give the jcl to run or the dataset it is in."
            )
        hit = protected_target(protected or [], args)
        if hit:
            raise PlanStepError(
                f"Step {index}: {hit[0]} is protected on this server ({hit[1]}) and cannot be changed."
            )
        try:
            times = int(raw.get("times") or 1)
        except (TypeError, ValueError) as exc:
            raise PlanStepError(f"Step {index}: times must be a whole number.") from exc
        if not 1 <= times <= MAX_TIMES:
            raise PlanStepError(f"Step {index}: times must be between 1 and {MAX_TIMES}.")
        cleaned.append({"tool": tool, "args": args, "times": times})
    return cleaned


def step_matches(step: dict[str, Any], tool: str, call_args: dict[str, Any]) -> bool:
    """True when a call is the change this step describes, and nothing more."""
    if step["tool"] != tool:
        return False
    step_args = step.get("args") or {}
    call = {k: v for k, v in call_args.items() if k not in _IGNORED_KEYS and v is not None}
    for key, value in step_args.items():
        if _norm(key, call.get(key)) != _norm(key, value):
            return False
    for key in call:
        if key in step_args:
            continue
        if key in CONTENT_KEYS and tool != "job.submit":
            continue  # the step left the exact text open, and its approval said so
        if call[key] is False or call[key] == "":
            continue  # an explicit default changes nothing
        return False
    return True


def find_step(
    steps: list[dict[str, Any]], uses: dict[int, int], tool: str, call_args: dict[str, Any],
) -> int | None:
    """Index of the first matching step with a use left, or None."""
    for index, step in enumerate(steps):
        if uses.get(index, 0) >= int(step.get("times") or 1):
            continue
        if step_matches(step, tool, call_args):
            return index
    return None


def step_target(step: dict[str, Any]) -> str:
    args = step.get("args") or {}
    dataset = args.get("dataset") or args.get("sourceDataset")
    member = args.get("member") or args.get("sourceMember")
    if dataset and member:
        text = f"{str(dataset).upper()}({str(member).upper()})"
    elif dataset:
        text = str(dataset).upper()
    elif args.get("path"):
        text = str(args["path"])
    elif args.get("command"):
        text = str(args["command"])
    elif args.get("jobId"):
        text = str(args["jobId"]).upper()
    else:
        text = ""
    if args.get("newDataset"):
        text += f" -> {str(args['newDataset']).upper()}"
    if args.get("newMember"):
        text += f" -> {str(args['newMember']).upper()}"
    if args.get("newPath"):
        text += f" -> {args['newPath']}"
    if args.get("targetDataset"):
        target = str(args["targetDataset"]).upper()
        if args.get("targetMember"):
            target += f"({str(args['targetMember']).upper()})"
        text += f" -> {target}"
    return text


def describe_step(step: dict[str, Any], index: int) -> str:
    """One step in plain words, for the person approving it."""
    args = step.get("args") or {}
    line = f"{index}. {step['tool']}  {step_target(step)}".rstrip()
    times = int(step.get("times") or 1)
    if times > 1:
        line += f"  (up to {times} times)"
    notes = []
    for key in sorted(CONTENT_KEYS):
        if key in args:
            size = len(args[key]) if isinstance(args[key], str) else len(json.dumps(args[key]))
            notes.append(f"{key}: fixed by this plan ({size} characters)")
    if step["tool"] == "job.submit" and "jcl" not in args:
        notes.append("runs the JCL in that dataset as it stands when the job is submitted")
    elif step["tool"] in _CONTENT_TOOLS and not any(k in args for k in CONTENT_KEYS):
        notes.append("the exact content is NOT fixed by this plan")
    extras = {k: v for k, v in args.items()
              if k not in CONTENT_KEYS and k not in _SHOWN_IN_TARGET}
    for key, value in sorted(extras.items()):
        notes.append(f"{key}: {value}")
    return line + "".join(f"\n     {note}" for note in notes)


_SHOWN_IN_TARGET = frozenset({
    "dataset", "member", "sourceDataset", "sourceMember", "targetDataset", "targetMember",
    "newDataset", "newMember", "path", "newPath", "command", "jobId",
})

# Tools whose effect is mostly their content.
_CONTENT_TOOLS = frozenset({"dataset.write", "member.write", "member.patch", "uss.write"})


def describe_steps(steps: list[dict[str, Any]]) -> str:
    if not steps:
        return "(no changes listed: this plan cannot change anything)"
    return "\n".join(describe_step(step, i) for i, step in enumerate(steps, start=1))


def remaining_steps(steps: list[dict[str, Any]], uses: dict[int, int]) -> list[str]:
    out = []
    for index, step in enumerate(steps):
        left = int(step.get("times") or 1) - uses.get(index, 0)
        if left > 0:
            out.append(f"{step['tool']} {step_target(step)}".strip())
    return out
