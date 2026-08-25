import pytest

from mainframe_workflow_mcp.clients.zowe_sdk import ZoweSdkMainframeClient

BIG = "\n".join(f"REC{i:05d} payroll detail line" for i in range(1, 501))
BIG = BIG.replace("REC00250 payroll detail line", "REC00250 ERROR THRESHOLD EXCEEDED")


class FakeFiles:
    def __init__(self, content):
        self.content = content
        self.request_endpoint = "https://host/zosmf/restfiles/"
        self.request_arguments = {"headers": {}}
        self.session_arguments = {}

    def get_dsn_content(self, target):
        return {"response": self.content}


def _client(content=BIG):
    return ZoweSdkMainframeClient(
        "zosmf", {"host_url": "h:1"},
        files=FakeFiles(content), jobs=object(), zosmf=object(),
    )


@pytest.mark.anyio
async def test_read_without_filters_returns_everything_unchanged():
    result = await _client().read_dataset({"profileName": "zosmf", "dataset": "HLQ.BIG"})
    assert result == {"content": BIG}
    assert "totalLines" not in result


@pytest.mark.anyio
async def test_search_text_returns_only_matching_lines_with_numbers():
    result = await _client().read_dataset(
        {"profileName": "zosmf", "dataset": "HLQ.BIG", "searchText": "THRESHOLD"}
    )
    assert result["matchCount"] == 1
    assert result["totalLines"] == 500
    assert result["content"] == "250: REC00250 ERROR THRESHOLD EXCEEDED"


@pytest.mark.anyio
async def test_search_is_case_insensitive_by_default_and_exact_when_asked():
    loose = await _client().read_dataset(
        {"profileName": "zosmf", "dataset": "HLQ.BIG", "searchText": "threshold"}
    )
    strict = await _client().read_dataset(
        {"profileName": "zosmf", "dataset": "HLQ.BIG",
         "searchText": "threshold", "caseSensitive": True}
    )
    assert loose["matchCount"] == 1
    assert strict["matchCount"] == 0


@pytest.mark.anyio
async def test_max_lines_caps_output_and_says_so():
    result = await _client().read_dataset(
        {"profileName": "zosmf", "dataset": "HLQ.BIG", "maxLines": 10}
    )
    assert result["truncated"] is True
    assert result["returnedLines"] == 10
    assert result["totalLines"] == 500
    assert len(result["content"].splitlines()) == 10


@pytest.mark.anyio
async def test_result_within_max_lines_is_not_marked_truncated():
    result = await _client().read_dataset(
        {"profileName": "zosmf", "dataset": "HLQ.BIG",
         "searchText": "THRESHOLD", "maxLines": 10}
    )
    assert result.get("truncated") is not True
    assert result["returnedLines"] == 1


@pytest.mark.anyio
async def test_regex_search_is_supported():
    result = await _client().read_dataset(
        {"profileName": "zosmf", "dataset": "HLQ.BIG",
         "searchText": r"REC0000[1-3] ", "regex": True}
    )
    assert result["matchCount"] == 3


@pytest.mark.anyio
async def test_no_match_returns_empty_content_not_the_whole_file():
    result = await _client().read_dataset(
        {"profileName": "zosmf", "dataset": "HLQ.BIG", "searchText": "NOTHING HERE"}
    )
    assert result["matchCount"] == 0
    assert result["content"] == ""
    assert result["totalLines"] == 500


@pytest.mark.anyio
async def test_read_member_filters_too():
    result = await _client().read_member(
        {"profileName": "zosmf", "dataset": "HLQ.SRC", "member": "PROG1",
         "searchText": "THRESHOLD"}
    )
    assert result["matchCount"] == 1


@pytest.mark.anyio
async def test_list_profiles_reports_the_bound_profile():
    result = await _client().list_profiles({})
    assert result == {"profiles": ["zosmf"], "default": "zosmf"}
