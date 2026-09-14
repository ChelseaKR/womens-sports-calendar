"""Ticketmaster Discovery API client.

Rate limit per docs/LICENSES-AND-ATTRIBUTION.md §2: the two official pages
disagree (2 vs 5 requests/second); 5000/day is consistent everywhere. This
client self-limits to 1 request/second, below both published numbers, and
tracks every request so the caller can print a crawl-budget report (bytes,
request count) per the repo's crawl-budget constraint.

Identifying User-Agent per the crawl-budget constraint: names the repo, no
secret in it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

DISCOVERY_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
USER_AGENT = "womens-sports-calendar/0.1 (+https://github.com/ChelseaKR/womens-sports-calendar)"
MIN_SECONDS_BETWEEN_REQUESTS = 1.0
PAGE_SIZE = 50


class TicketmasterFetchError(RuntimeError):
    """Raised when a Discovery API call fails after retries. A failed fetch
    fails the build -- callers must not swallow this."""


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

    def __enter__(self) -> "DiscoveryClient":
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

    def search_team_events(
        self,
        team_slug: str,
        team_name: str,
        country_codes: tuple[str, ...],
    ) -> tuple[list[dict], bool]:
        """Return (raw Discovery API event dicts, truncated) for one team.
        One call per country in country_codes (the API takes a single
        countryCode per call). Paginates only within the API's first page;
        a team whose result spans more than one page comes back with
        truncated=True so the caller can surface it in the coverage report
        rather than silently dropping events past page 1.
        """
        events: list[dict] = []
        truncated = False
        for country in country_codes:
            country_events, country_truncated = self._search_one(team_slug, team_name, country)
            events.extend(country_events)
            truncated = truncated or country_truncated
        # de-duplicate by event id (a team can appear in more than one
        # country query near a border, or across paginated calls)
        seen: set[str] = set()
        deduped = []
        for event in events:
            event_id = event.get("id")
            if event_id in seen:
                continue
            seen.add(event_id)
            deduped.append(event)
        return deduped, truncated

    def _search_one(self, team_slug: str, team_name: str, country_code: str) -> tuple[list[dict], bool]:
        params = {
            "apikey": self._api_key,
            "keyword": team_name,
            "classificationName": "Sports",
            "countryCode": country_code,
            "size": str(PAGE_SIZE),
            "sort": "date,asc",
        }
        payload = self._get_with_retry(params)
        page = payload.get("page", {})
        truncated = page.get("totalPages", 1) > 1
        return payload.get("_embedded", {}).get("events", []), truncated

    def _get_with_retry(self, params: dict[str, str]) -> dict:
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
                return response.json()
            if response.status_code == 429:
                # Respect the API's own backoff signal rather than hammering it.
                retry_after = float(response.headers.get("Retry-After", "2"))
                time.sleep(retry_after)
                last_error = TicketmasterFetchError(
                    f"429 rate limited on attempt {attempt}"
                )
                continue
            last_error = TicketmasterFetchError(
                f"Discovery API returned {response.status_code} for "
                f"keyword={params.get('keyword')!r}: {response.text[:300]}"
            )
        raise TicketmasterFetchError(
            f"failed after {self._max_retries} attempts for "
            f"keyword={params.get('keyword')!r}: {last_error}"
        )
