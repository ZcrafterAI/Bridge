import pytest
from mainframe_workflow_mcp._toolbox import list_tool_definitions
from mainframe_workflow_mcp.plan_steps import (
    PlanStepError,
    describe_steps,
    find_step,
    protected_pattern,
    step_matches,
    validate_steps,
)

DEFS = list_tool_definitions()


def check(steps, protected=None):
    return validate_steps(steps, DEFS, protected or [])


def test_a_plan_without_steps_is_valid_and_empty():
    assert check(None) == []
    assert check([]) == []


def test_a_step_keeps_its_tool_target_and_count():
    assert check([{"tool": "member.write", "args": {"dataset": "HLQ.SRC", "member": "A"}, "times": 2}]) == [
        {"tool": "member.write", "args": {"dataset": "HLQ.SRC", "member": "A"}, "times": 2}
    ]


@pytest.mark.parametrize("steps, message", [
    ("nope", "must be a list"),
    ([{"tool": "nope.tool", "args": {}}], "no such tool"),
    ([{"tool": "dataset.read", "args": {"dataset": "HLQ.A"}}], "only reads"),
    ([{"tool": "member.write", "args": {"dataset": "HLQ.SRC"}}], "must name member"),
    ([{"tool": "member.write", "args": {"dataset": "HLQ.SRC", "member": "A", "bogus": 1}}], "no argument bogus"),
    ([{"tool": "job.submit", "args": {}}], "jcl to run or the dataset"),
    ([{"tool": "tso.command", "args": {}}], "must name command"),
    ([{"tool": "dataset.delete", "args": {"dataset": "HLQ.A"}, "times": 99}], "between 1 and"),
])
def test_bad_steps_are_refused_with_a_reason(steps, message):
    with pytest.raises(PlanStepError, match=message):
        check(steps)


def test_a_step_on_a_protected_dataset_is_refused():
    with pytest.raises(PlanStepError, match="protected"):
        check([{"tool": "dataset.delete", "args": {"dataset": "sys1.proclib"}}], ["SYS1.**"])
    with pytest.raises(PlanStepError, match="protected"):
        check([{"tool": "dataset.rename", "args": {"dataset": "HLQ.A", "newDataset": "PAY.PROD.A"}}], ["*.PROD.**"])


def test_protected_patterns():
    assert protected_pattern(["SYS1.**"], "SYS1.PROCLIB") == "SYS1.**"
    assert protected_pattern(["*.PROD.**"], "PAY.PROD.MASTER") == "*.PROD.**"
    assert protected_pattern(["*.PROD.**"], "PAY.TEST.MASTER") is None
    assert protected_pattern(["HLQ.*"], "HLQ.A.B") is None  # one * is one qualifier


def test_a_call_matches_only_the_change_the_step_describes():
    step = check([{"tool": "member.write", "args": {"dataset": "HLQ.SRC", "member": "PAYCALC"}}])[0]
    assert step_matches(step, "member.write", {"dataset": "hlq.src", "member": "paycalc", "content": "x"})
    assert not step_matches(step, "member.write", {"dataset": "HLQ.SRC", "member": "OTHER", "content": "x"})
    assert not step_matches(step, "member.delete", {"dataset": "HLQ.SRC", "member": "PAYCALC"})
    assert not step_matches(step, "member.write", {"dataset": "HLQ.PROD", "member": "PAYCALC", "content": "x"})


def test_content_fixed_by_the_step_must_be_sent_exactly():
    step = check([{"tool": "member.write", "args": {"dataset": "HLQ.SRC", "member": "A", "content": "LINE 1\n"}}])[0]
    assert step_matches(step, "member.write", {"dataset": "HLQ.SRC", "member": "A", "content": "LINE 1\n"})
    assert not step_matches(step, "member.write", {"dataset": "HLQ.SRC", "member": "A", "content": "LINE 2\n"})


def test_an_argument_the_step_did_not_name_is_refused():
    step = check([{"tool": "dataset.copy", "args": {"sourceDataset": "HLQ.A", "targetDataset": "HLQ.B"}}])[0]
    assert step_matches(step, "dataset.copy", {"sourceDataset": "HLQ.A", "targetDataset": "HLQ.B", "replace": False})
    assert not step_matches(step, "dataset.copy", {"sourceDataset": "HLQ.A", "targetDataset": "HLQ.B", "replace": True})
    assert not step_matches(
        step, "dataset.copy", {"sourceDataset": "HLQ.A", "targetDataset": "HLQ.B", "targetMember": "X"}
    )


def test_a_command_step_fixes_the_exact_command():
    step = check([{"tool": "tso.command", "args": {"command": "DELETE 'HLQ.OLD'"}}])[0]
    assert step_matches(step, "tso.command", {"command": " DELETE 'HLQ.OLD' "})
    assert not step_matches(step, "tso.command", {"command": "DELETE 'HLQ.PROD'"})


def test_submit_from_a_dataset_cannot_carry_other_jcl():
    step = check([{"tool": "job.submit", "args": {"dataset": "HLQ.JCL(RUN)"}}])[0]
    assert step_matches(step, "job.submit", {"dataset": "HLQ.JCL(RUN)"})
    assert not step_matches(step, "job.submit", {"dataset": "HLQ.JCL(RUN)", "jcl": "//EVIL JOB"})


def test_each_step_is_used_as_often_as_it_says():
    steps = check([
        {"tool": "job.submit", "args": {"dataset": "HLQ.JCL(RUN)"}, "times": 2},
        {"tool": "dataset.delete", "args": {"dataset": "HLQ.OLD"}},
    ])
    call = {"dataset": "HLQ.JCL(RUN)"}
    assert find_step(steps, {}, "job.submit", call) == 0
    assert find_step(steps, {0: 1}, "job.submit", call) == 0
    assert find_step(steps, {0: 2}, "job.submit", call) is None
    assert find_step(steps, {1: 1}, "dataset.delete", {"dataset": "HLQ.OLD"}) is None


def test_the_person_is_told_when_content_is_not_fixed():
    text = describe_steps(check([
        {"tool": "member.write", "args": {"dataset": "HLQ.SRC", "member": "A"}},
        {"tool": "member.write", "args": {"dataset": "HLQ.SRC", "member": "B", "content": "X"}},
        {"tool": "job.submit", "args": {"dataset": "HLQ.JCL(RUN)"}},
    ]))
    assert "1. member.write  HLQ.SRC(A)" in text
    assert "NOT fixed" in text.split("2. member.write")[0]
    assert "fixed by this plan" in text.split("2. member.write")[1]
    assert "as it stands when the job is submitted" in text
    assert "cannot change anything" in describe_steps([])
