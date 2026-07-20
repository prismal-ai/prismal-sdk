"""SSE frame parser tests (CSB-02-02, SPEC-CSB-CHT-002/005)."""

from __future__ import annotations

from prismal_sdk._sse import iter_sse_events


def _lines(text: str) -> list[str]:
    """Split pre-framed SSE text into the line-without-newline shape httpx yields."""
    return text.split("\n")[:-1]  # drop the trailing "" from a final \n


def test_named_event_parsed():
    text = 'event: token\ndata: {"delta":"hi"}\n\n'
    frames = list(iter_sse_events(_lines(text)))
    assert frames == [("token", '{"delta":"hi"}')]


def test_heartbeat_comment_ignored():
    text = ": heartbeat\n\nevent: done\ndata: {}\n\n"
    frames = list(iter_sse_events(_lines(text)))
    assert frames == [("done", "{}")]


def test_multiple_events_in_order():
    text = (
        'event: token\ndata: {"delta":"a"}\n\n'
        'event: token\ndata: {"delta":"b"}\n\n'
        "event: done\ndata: {}\n\n"
    )
    frames = list(iter_sse_events(_lines(text)))
    assert [f[0] for f in frames] == ["token", "token", "done"]


def test_multiline_data_joined_with_newline():
    text = "event: state\ndata: line1\ndata: line2\n\n"
    frames = list(iter_sse_events(_lines(text)))
    assert frames == [("state", "line1\nline2")]
