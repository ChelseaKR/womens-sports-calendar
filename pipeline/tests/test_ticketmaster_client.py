from __future__ import annotations

import httpx
import pytest

from wsc_pipeline.ticketmaster import DiscoveryClient, TicketmasterFetchError

ONE_PAGE_RESPONSE = {
    "_embedded": {"events": [{"id": "EVT1", "name": "Indiana Fever vs New York Liberty"}]},
    "page": {"totalPages": 1},
}
TWO_PAGE_RESPONSE = {
    "_embedded": {"events": [{"id": "EVT1", "name": "Indiana Fever vs New York Liberty"}]},
    "page": {"totalPages": 2},
}


def _client_with_transport(handler) -> DiscoveryClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return DiscoveryClient("fake-key", client=http_client, min_interval=0.0)


def test_search_team_events_returns_events_and_not_truncated():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ONE_PAGE_RESPONSE)

    client = _client_with_transport(handler)
    events, truncated = client.search_team_events("indiana-fever", "Indiana Fever", ("US",))
    assert len(events) == 1
    assert events[0]["id"] == "EVT1"
    assert truncated is False


def test_search_team_events_reads_every_page_instead_of_only_the_first():
    """The 2026-09-17 live build flagged two teams whose keyword search ran
    past one page; reading page 0 alone left their later results unread.
    Every page the API reports must be read, and the result is then
    complete (truncated=False)."""
    pages_requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "0")
        pages_requested.append(page)
        return httpx.Response(
            200,
            json={
                "_embedded": {"events": [{"id": f"EVT-page{page}", "name": "Indiana Fever vs New York Liberty"}]},
                "page": {"totalPages": 3, "totalElements": 3, "number": int(page)},
            },
        )

    client = _client_with_transport(handler)
    events, truncated = client.search_team_events("indiana-fever", "Indiana Fever", ("US",))
    assert pages_requested == ["0", "1", "2"]
    assert [e["id"] for e in events] == ["EVT-page0", "EVT-page1", "EVT-page2"]
    assert truncated is False


def test_search_team_events_flags_truncation_instead_of_silently_dropping():
    """Only a result with pages left after MAX_PAGES_PER_QUERY is flagged,
    and it is flagged rather than silently cut off."""
    import wsc_pipeline.ticketmaster as tm_module

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={**TWO_PAGE_RESPONSE, "page": {"totalPages": 99}})

    client = _client_with_transport(handler)
    _events, truncated = client.search_team_events("indiana-fever", "Indiana Fever", ("US",))
    assert truncated is True
    assert calls["n"] == tm_module.MAX_PAGES_PER_QUERY


def test_reported_matches_with_no_events_is_a_failed_fetch_not_no_games():
    """A response that says it matched events but carries none is a broken
    response; treating it as "this team has no games" would publish an
    empty calendar as fact."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"page": {"totalElements": 7, "totalPages": 1, "number": 0}})

    client = _client_with_transport(handler)
    with pytest.raises(TicketmasterFetchError):
        client.search_team_events("indiana-fever", "Indiana Fever", ("US",))


def test_a_real_zero_result_response_is_not_an_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"page": {"size": 50, "totalElements": 0, "totalPages": 0, "number": 0}})

    client = _client_with_transport(handler)
    events, truncated = client.search_team_events("indiana-fever", "Indiana Fever", ("US",))
    assert events == [] and truncated is False


def test_search_team_events_dedupes_across_countries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ONE_PAGE_RESPONSE)

    client = _client_with_transport(handler)
    events, _truncated = client.search_team_events("pwhl-team", "PWHL Team", ("US", "CA"))
    assert len(events) == 1  # same event id from both country queries, deduped


def test_failed_fetch_raises_after_retries_never_returns_partial_success():
    """A failed fetch fails the build -- the client must raise, not return
    an empty-but-'successful' result that would let the pipeline publish a
    silently-thinned site."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    client = _client_with_transport(handler)
    with pytest.raises(TicketmasterFetchError):
        client.search_team_events("indiana-fever", "Indiana Fever", ("US",))


def test_rate_limit_429_retries_after_backoff_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, text="slow down")
        return httpx.Response(200, json=ONE_PAGE_RESPONSE)

    client = _client_with_transport(handler)
    events, _truncated = client.search_team_events("indiana-fever", "Indiana Fever", ("US",))
    assert len(events) == 1
    assert calls["n"] == 2


def test_crawl_budget_records_requests_and_bytes():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ONE_PAGE_RESPONSE)

    client = _client_with_transport(handler)
    client.search_team_events("indiana-fever", "Indiana Fever", ("US",))
    assert client.budget.requests_made == 1
    assert client.budget.bytes_received > 0


def test_throttle_sleeps_between_consecutive_requests(monkeypatch):
    """Crawl-budget constraint: sequential requests >=1s apart. Verified by
    checking the throttle actually calls time.sleep with a positive
    duration on the second request when min_interval > 0, using a fake
    clock so the test itself does not take a full second."""
    fake_time = {"t": 0.0}
    sleeps: list[float] = []

    def fake_monotonic():
        return fake_time["t"]

    def fake_sleep(seconds: float):
        sleeps.append(seconds)
        fake_time["t"] += seconds

    def handler(request: httpx.Request) -> httpx.Response:
        fake_time["t"] += 0.01  # simulate negligible request duration
        return httpx.Response(200, json=ONE_PAGE_RESPONSE)

    import wsc_pipeline.ticketmaster as tm_module

    monkeypatch.setattr(tm_module.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(tm_module.time, "sleep", fake_sleep)

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = DiscoveryClient("fake-key", client=http_client, min_interval=1.0)

    client.search_team_events("indiana-fever", "Indiana Fever", ("US", "CA"))
    # Two requests (one per country) with min_interval=1.0s: the second
    # request must have been throttled by roughly 1.0 - 0.01s.
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(0.99, abs=0.01)
