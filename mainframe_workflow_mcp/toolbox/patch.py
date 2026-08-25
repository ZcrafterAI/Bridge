"""Unified-diff application. Real package's `patch.apply_unified_diff`."""
from __future__ import annotations


def apply_unified_diff(original: str, diff: str) -> str:
    """Apply a unified diff to `original`, returning the patched text.

    Strict: a context or removal line that does not match the source raises,
    rather than silently producing a wrong member — which is the behaviour a
    mainframe patch tool must have.
    """
    src = original.splitlines()
    out: list[str] = []
    pos = 0
    lines = diff.splitlines()
    i = 0
    saw_hunk = False

    while i < len(lines):
        line = lines[i]
        if line.startswith("--- ") or line.startswith("+++ "):
            i += 1
            continue
        if line.startswith("@@"):
            saw_hunk = True
            # @@ -start,count +start,count @@
            try:
                old_part = line.split()[1]          # -start,count
                start = int(old_part[1:].split(",")[0])
            except (IndexError, ValueError) as exc:
                raise ValueError(f"malformed hunk header: {line!r}") from exc
            target = max(start - 1, 0)
            if target < pos:
                raise ValueError("hunks out of order or overlapping")
            out.extend(src[pos:target])
            pos = target
            i += 1
            while i < len(lines) and not lines[i].startswith("@@"):
                h = lines[i]
                if h.startswith("+"):
                    out.append(h[1:])
                elif h.startswith("-"):
                    if pos >= len(src) or src[pos] != h[1:]:
                        found = src[pos] if pos < len(src) else "<past end of file>"
                        raise ValueError(
                            f"diff does not apply: expected {h[1:]!r} at line {pos + 1}, found {found!r}"
                        )
                    pos += 1
                elif h.startswith(" ") or h == "":
                    ctx = h[1:] if h else ""
                    if pos >= len(src) or src[pos] != ctx:
                        found = src[pos] if pos < len(src) else "<past end of file>"
                        raise ValueError(
                            f"context mismatch: expected {ctx!r} at line {pos + 1}, found {found!r}"
                        )
                    out.append(src[pos])
                    pos += 1
                elif h.startswith("\\"):
                    pass  # "\ No newline at end of file"
                else:
                    raise ValueError(f"unrecognized diff line: {h!r}")
                i += 1
            continue
        i += 1

    if not saw_hunk:
        raise ValueError("no hunks found in diff")

    out.extend(src[pos:])
    trailing = "\n" if original.endswith("\n") else ""
    return "\n".join(out) + trailing
