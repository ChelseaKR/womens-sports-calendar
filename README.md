# womens-sports-calendar (working name)

Subscribable `.ics` calendar feeds per league and team for women's pro sports,
plus a ticket-price finder, built nightly from the leagues' own public schedule
feeds and the Ticketmaster Discovery API. No account, no tracking, no script
from anyone but us on the page. Monetised only by plain affiliate URLs.

[moved to private strategy notes]

## Shape

- `pipeline/` — Python. Reads each league's public schedule source (only where
  its terms permit reuse — see `docs/LICENSES-AND-ATTRIBUTION.md`), joins
  Ticketmaster Discovery events and price ranges by venue + date, and emits one
  `.ics` per league and per team plus the site's data. Nightly; no human step.
- `site/` — static HTML. One page per league and team: the subscribe link, the
  next games, the price range, and one affiliate link per game. No JavaScript
  that talks to anyone but us; no cookies; no analytics.
- `docs/` — research, decisions, licences and attributions.

## Not yet decided

The name and the domain. A subdomain of chelseakr.com is the default until
then.
