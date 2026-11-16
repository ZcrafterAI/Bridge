"""Rules for TSO commands: which only read, and which are refused outright.

`tso.query` runs without approval, so it must never change anything. It takes a short list
of listing commands and refuses the operands that make a listing command write a dataset.
"""
from __future__ import annotations

import re

# TSO commands that list or display, never change.
TSO_QUERY_COMMANDS = (
    "LISTCAT", "LISTC", "LISTDS", "LISTALC", "LISTA", "LISTUSER", "LU",
    "LISTGRP", "LG", "RLIST", "RL", "SEARCH", "STATUS", "ST", "TIME", "HELP", "H",
)

ONE_LINE = "A TSO command is one line, with no line breaks or control characters."
SUBMIT_REFUSAL = (
    "TSO SUBMIT is not run: submit the job with job.submit, whose plan step shows the JCL "
    "or the dataset it comes from."
)


def command_verb(command: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9@#$%]+)", command)
    return match.group(1).upper() if match else ""


def has_control_character(command: str) -> bool:
    """A line break or other control character could start a second command."""
    for char in command:
        code = ord(char)
        if code < 0x20 or 0x7F <= code <= 0x9F or code in (0x2028, 0x2029):
            return True
    return False


def submits(command: str) -> bool:
    return re.fullmatch(r"SUB(M(I(T)?)?)?", command_verb(command)) is not None


def writing_operand(command: str) -> str | None:
    """The operand that makes a listing command write a dataset, or None.

    RACF SEARCH has CLIST, which creates a CLIST, and LISTCAT has OUTFILE. Keywords are read
    the way TSO reads them: outside quotes and parentheses, and abbreviated (CLI, OFILE), so
    ENT('A.CLIST') is not an operand.
    """
    words: list[str] = []
    word = ""
    quoted = False
    depth = 0
    for char in command.strip() + " ":
        if char == "'":
            quoted = not quoted
        if quoted:
            continue
        if char in "()" or (depth == 0 and (char.isspace() or char == ",")):
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            if word:
                words.append(word)
            word = ""
        elif depth == 0 and char != "'":
            word += char
    for operand in words[1:]:
        keyword = operand.upper()
        if re.fullmatch(r"CLI(S|ST)?", keyword) or re.fullmatch(r"(OUTF(I|IL|ILE)?|OFILE)", keyword):
            return operand
    return None


def is_query(command: str) -> bool:
    text = command.strip()
    return (
        not has_control_character(text)
        and command_verb(text) in TSO_QUERY_COMMANDS
        and writing_operand(text) is None
    )
