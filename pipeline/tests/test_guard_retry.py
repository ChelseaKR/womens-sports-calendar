"""A previous-feed read is retried before the publish guard counts the feed as
unreadable (DECISIONS 0045, docs/adr/0006).

On 2026-11-18 one HTTP 503 while re-reading a team feed refused the whole
nightly publish (docs/incidents/2026-11-18-stale-listings-503.md). A request
that times out, cannot connect, or gets HTTP 429 or 5xx is now tried up to
three times, 2 s and 4 s apart; a 404 or any other status is an answer and is
never retried. Once retries stop, the guard behaves exactly as before.

No test touches the network: every read goes through an httpx.MockTransport,
and guard._sleep is replaced so the waits are recorded, not waited.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from wsc_pipeline import config, guard
from wsc_pipeline.guard import PreviousPublish

from .conftest import REAL_FETCH_PREVIOUS_PUBLISH
from .test_publish_guard import BASE_URL, _feed_bytes, _run

LIBERTY_FEED = "/ics/wnba/new-york-liberty.ics"
WNBA_LEAGUE_FEED = "/ics/wnba.ics"
# A fetched feed with no games: the previous publish then has nothing to
# lose, so the only thing that can refuse the build is an unreadable feed.
EMPTY_FEED = _feed_bytes([])


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(guard, "_sleep", recorded.append)
    return recorded


def _site(failing_path: str, failures: list[httpx.Response | Exception]) -> tuple[Callable, list[str]]:
    """The live site, where `failing_path` answers with `failures` in turn
    (an exception is raised, as a transport error is) and then 200, and every
    other feed is a readable empty one. Returns the handler and every path
    requested, in order."""
    calls: list[str] = []
    pending = list(failures)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        if path == failing_path and pending:
            failure = pending.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return failure
        return httpx.Response(200, content=EMPTY_FEED)

    return handler, calls


def _fetch(handler: Callable[[httpx.Request], httpx.Response]) -> PreviousPublish:
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return REAL_FETCH_PREVIOUS_PUBLISH(BASE_URL, client=client)


def test_a_503_is_retried_and_the_feed_is_read_on_the_next_attempt(waits, capsys):
    """The 2026-11-18 incident: one 503, then the site answers."""
    handler, calls = _site(LIBERTY_FEED, [httpx.Response(503)])
    previous = _fetch(handler)

    assert calls.count(LIBERTY_FEED) == 2
    assert ("wnba", "new-york-liberty") in previous.games
    assert previous.unreadable == {} and previous.unreadable_feeds == {}
    assert previous.fully_read
    assert waits == [2.0]
    log = capsys.readouterr().err
    assert f"{BASE_URL}{LIBERTY_FEED}: HTTP 503; retrying in 2 s (attempt 2 of 3)" in log
    assert not _run(previous, []).refused


def test_a_feed_that_answers_503_every_time_is_given_up_on_and_the_guard_still_refuses(waits, capsys):
    handler, calls = _site(LIBERTY_FEED, [httpx.Response(503)] * 10)
    previous = _fetch(handler)

    assert calls.count(LIBERTY_FEED) == guard._ATTEMPTS == 3
    assert waits == [2.0, 4.0]
    # Exactly what the guard recorded before retries existed.
    assert previous.unreadable == {("wnba", "new-york-liberty"): "HTTP 503"}
    report = _run(previous, [])
    assert report.refused
    [violation] = report.violations
    assert violation.league_slug == "wnba" and violation.rule == guard.UNREADABLE_RULE
    assert "ics/wnba/new-york-liberty.ics (HTTP 503)" in violation.message
    log = capsys.readouterr().err
    assert "retrying in 2 s (attempt 2 of 3)" in log and "retrying in 4 s (attempt 3 of 3)" in log


def test_a_404_is_a_new_feed_and_is_never_retried(waits):
    handler, calls = _site(LIBERTY_FEED, [httpx.Response(404)])
    previous = _fetch(handler)

    assert calls.count(LIBERTY_FEED) == 1
    assert waits == []
    assert ("wnba", "new-york-liberty") in previous.new_teams
    assert previous.unreadable == {}


@pytest.mark.parametrize("status", [400, 401, 403, 410, 418])
def test_any_other_4xx_is_not_retried_and_counts_as_unreadable_at_once(waits, status):
    handler, calls = _site(LIBERTY_FEED, [httpx.Response(status)])
    previous = _fetch(handler)

    assert calls.count(LIBERTY_FEED) == 1
    assert waits == []
    assert previous.unreadable == {("wnba", "new-york-liberty"): f"HTTP {status}"}
    assert _run(previous, []).refused


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(429),
        httpx.Response(500),
        httpx.Response(502),
        httpx.Response(504),
        httpx.ReadTimeout("slow"),
        httpx.ConnectTimeout("slow"),
        httpx.ConnectError("no route"),
        httpx.ReadError("reset"),
        httpx.RemoteProtocolError("server disconnected"),
    ],
    ids=lambda f: str(f.status_code) if isinstance(f, httpx.Response) else type(f).__name__,
)
def test_a_429_5xx_timeout_or_connection_error_is_retried(waits, failure):
    handler, calls = _site(LIBERTY_FEED, [failure, failure])
    previous = _fetch(handler)

    assert calls.count(LIBERTY_FEED) == 3
    assert waits == [2.0, 4.0]
    assert previous.unreadable == {}


def test_a_transport_error_on_every_attempt_is_recorded_as_before(waits):
    handler, calls = _site(LIBERTY_FEED, [httpx.ConnectError("no route")] * 3)
    previous = _fetch(handler)

    assert calls.count(LIBERTY_FEED) == 3
    assert previous.unreadable == {("wnba", "new-york-liberty"): "request failed (ConnectError)"}
    assert _run(previous, []).refused


def test_an_error_that_is_not_transient_is_not_retried(waits):
    handler, calls = _site(LIBERTY_FEED, [httpx.TooManyRedirects("loop")])
    previous = _fetch(handler)

    assert calls.count(LIBERTY_FEED) == 1
    assert waits == []
    assert previous.unreadable == {("wnba", "new-york-liberty"): "request failed (TooManyRedirects)"}


def test_a_league_feed_is_retried_too(waits):
    handler, calls = _site(WNBA_LEAGUE_FEED, [httpx.Response(503)])
    previous = _fetch(handler)

    assert calls.count(WNBA_LEAGUE_FEED) == 2
    assert previous.unreadable_feeds == {}
    assert previous.fully_read


def test_a_site_that_answers_503_everywhere_spends_the_budget_once_and_refuses_every_league(waits, capsys):
    """The run-wide budget bounds the added wall time when the site is down
    for good: at most _RETRY_BUDGET retries, then one attempt per feed."""
    calls: list[str] = []

    def down(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(503)

    previous = _fetch(down)
    feeds = len(config.all_teams()) + len(config.LEAGUES)
    assert len(calls) == feeds + guard._RETRY_BUDGET
    assert waits == [2.0, 4.0] * (guard._RETRY_BUDGET // 2)
    assert sum(waits) == 18.0
    assert len(previous.unreadable) == len(config.all_teams())
    assert set(previous.unreadable.values()) == {"HTTP 503"}
    report = _run(previous, [])
    assert {v.league_slug for v in report.violations} == {lg.slug for lg in config.LEAGUES}
    assert all(v.rule == guard.UNREADABLE_RULE for v in report.violations)
    assert capsys.readouterr().err.count("retries this build allows are spent") == 1
