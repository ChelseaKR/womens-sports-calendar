"""Ticketmaster Discovery API client.

Rate limit per docs/LICENSES-AND-ATTRIBUTION.md §2: the two official pages
disagree (2 vs 5 requests/second); 5000/day is consistent everywhere. This
client self-limits to 1 request/second, below both published numbers, and
tracks every request so the caller can print a crawl-budget report (bytes,
request count) per the repo's crawl-budget constraint.

Identifying User-Agent per the crawl-budget constraint: names the product
and its public site, no secret in it. It used to point at the GitHub repo,
which is private -- a contact URL that 404s for Ticketmaster and names the
private repo is worse than none.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

DISCOVERY_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
USER_AGENT = "NextHomeGame/0.1 (+https://nexthomegame.com/)"
MIN_SECONDS_BETWEEN_REQUESTS = 1.0
PAGE_SIZE = 50
# Pages read per (team, country) query before giving up and flagging the
# result as possibly incomplete. The live build of 2026-09-17 had two
# teams (connecticut-sun, racing-louisville) whose keyword search ran past
# one 50-event page -- keyword false positives count toward the page -- so
# reading only page 0 left their later-dated results unread. 5 x 50 = 250
# events is several seasons of home games, and well inside the Discovery
# API's deep-paging limit (size * page < 1000).
MAX_PAGES_PER_QUERY = 5


class TicketmasterFetchError(RuntimeError):
    """Raised when a Discovery API call fails after retries. A failed fetch
    fails the build -- callers must not swallow this."""


def _json_object(response: httpx.Response, keyword: str | None) -> dict[str, Any]:
    """The 200 response body as a JSON object. A body that is not JSON, or
    is JSON but not an object, is a failed fetch (TicketmasterFetchError),
    not a crash with a traceback and not an empty result."""
    try:
        payload = response.json()
    except ValueError as exc:
        raise TicketmasterFetchError(f"Discovery API returned a non-JSON 200 body for keyword={keyword!r}") from exc
    if not isinstance(payload, dict):
        raise TicketmasterFetchError(
            f"Discovery API returned a 200 body that is not a JSON object for keyword={keyword!r}"
        )
    return payload


@dataclass
class CrawlBudget:
    """Tracks what the pipeline actually did, for the coverage/crawl report."""

    requests_made: int = 0
    bytes_received: int = 0
    requests_by_team: dict[str, int] = field(default_factory=dict)

    def record(self, team_slug: str, response: httpx.Response) -> None:
        self.requests_made += 1
        self.bytes_received += len(response.content)
        self.requests_by_team[team_slug] = self.requests_by_team.get(team_slug, 0) + 1


class DiscoveryClient:
    """Sequential, rate-limited client. One team keyword search per call."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        min_interval: float = MIN_SECONDS_BETWEEN_REQUESTS,
        max_retries: int = 3,
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=20.0, headers={"User-Agent": USER_AGENT})
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_request_at: float | None = None
        self.budget = CrawlBudget()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> DiscoveryClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            remaining = self._min_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def _redact(self, message: str) -> str:
        """The message with the API key replaced. An error body or an HTTP
        exception can echo the request URL, and the key travels in its query
        string; these messages reach stderr, the build log and the job
        summary (OBSERVABILITY-STANDARD OBS-11: never log a credential).
        GitHub masks the secret in Actions logs; a local run has no mask."""
        if not self._api_key:
            return message
        return message.replace(self._api_key, "[redacted]")

    def search_team_events(
        self,
        team_slug: str,
        team_name: str,
        country_codes: tuple[str, ...],
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return (raw Discovery API event dicts, truncated) for one team.
        One query per country in country_codes (the API takes a single
        countryCode per call), each read page by page until the API says
        there are no more pages. Only a result that still has pages left
        after MAX_PAGES_PER_QUERY comes back with truncated=True, so the
        caller can say "possibly incomplete" on the site and in the
        coverage report instead of publishing the first page as the whole
        schedule.
        """
        events: list[dict[str, Any]] = []
        truncated = False
        for country in country_codes:
            country_events, country_truncated = self._search_one(team_slug, team_name, country)
            events.extend(country_events)
            truncated = truncated or country_truncated
        # de-duplicate by event id (a team can appear in more than one
        # country query near a border, or across paginated calls)
        seen: set[str | None] = set()
        deduped = []
        for event in events:
            event_id = event.get("id")
            if event_id in seen:
                continue
            seen.add(event_id)
            deduped.append(event)
        return deduped, truncated

    def _search_one(self, team_slug: str, team_name: str, country_code: str) -> tuple[list[dict[str, Any]], bool]:
        events: list[dict[str, Any]] = []
        page_number = 0
        while True:
            params = {
                "apikey": self._api_key,
                "keyword": team_name,
                "classificationName": "Sports",
                "countryCode": country_code,
                "size": str(PAGE_SIZE),
                "page": str(page_number),
                "sort": "date,asc",
            }
            try:
                payload = self._get_with_retry(params)
            except TicketmasterFetchError as exc:
                # `from None`: the chained original still carries the key.
                raise TicketmasterFetchError(self._redact(str(exc))) from None
            page = payload.get("page") or {}
            page_events = (payload.get("_embedded") or {}).get("events") or []
            total_elements = page.get("totalElements")
            if not page_events and isinstance(total_elements, int) and total_elements > 0 and page_number == 0:
                # The API says there are matches but sent none: a malformed
                # or partial response, not "this team has no games".
                raise TicketmasterFetchError(
                    f"Discovery API reported {total_elements} events for "
                    f"keyword={team_name!r} but returned none on page 0"
                )
            events.extend(page_events)
            page_number += 1
            total_pages = page.get("totalPages", 1)
            if not isinstance(total_pages, int) or page_number >= total_pages:
                return events, False
            if page_number >= MAX_PAGES_PER_QUERY:
                return events, True

    def _get_with_retry(self, params: dict[str, str]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            self._throttle()
            try:
                response = self._client.get(DISCOVERY_URL, params=params)
            except httpx.HTTPError as exc:
                last_error = exc
                continue
            self.budget.record(params.get("keyword", "?"), response)
            if response.status_code == 200:
                return _json_object(response, params.get("keyword"))
            if response.status_code == 429:
                # Respect the API's own backoff signal rather than hammering it.
                retry_after = float(response.headers.get("Retry-After", "2"))
                time.sleep(retry_after)
                last_error = TicketmasterFetchError(f"429 rate limited on attempt {attempt}")
                continue
            last_error = TicketmasterFetchError(
                f"Discovery API returned {response.status_code} for "
                f"keyword={params.get('keyword')!r}: {response.text[:300]}"
            )
        raise TicketmasterFetchError(
            f"failed after {self._max_retries} attempts for keyword={params.get('keyword')!r}: {last_error}"
        )
