# Incidents

INCIDENT-RESPONSE-STANDARD (vendored in `docs/standards/`) sets the
severity ladder, the labels and the secret-leak runbook. This directory
holds the postmortems.

## Opening an incident

Open a GitHub issue in this repository as soon as an event meets the bar,
labelled `incident` plus exactly one of `sev1`–`sev4`, and `deploy-caused`
when it began within 24 hours of a deploy. What each level means here:

| Severity | Examples for this site |
|---|---|
| SEV1 | The Ticketmaster API key or another credential reaches a public surface. The site or its feeds are down for everyone. |
| SEV2 | Live listings are past their 30-hour SLA (`freshness.yml` opens this one itself, labelled `stale-data`). Feeds publish wrong games as current. A secret is caught before it is pushed. |
| SEV3 | Some pages or feeds are wrong for some teams. A CI gate found silently disabled. |
| SEV4 | A near miss: a control almost failed, with no user impact. |

For a leaked credential, follow the runbook in
`docs/standards/INCIDENT-RESPONSE-STANDARD.md` §4 and `SECURITY.md`:
rotate, revoke, check the provider's logs, record the history-scrub
decision, close the entry point.

## Postmortems

Each closed SEV1 or SEV2 issue gets `docs/incidents/YYYY-MM-DD-<slug>.md`
within 7 days (SEV3: 14 days), blameless, with these sections:

```markdown
# Incident: <one-line description> — YYYY-MM-DD

**Severity:** SEVn · **Status:** Resolved · **Related issue:** #NN

## Summary
## Timeline (UTC)
## Impact
## Detection
## Root cause
## What went well
## What went poorly
## Action items
| Action | Owner | Due | Tracking issue |
|---|---|---|---|
## Related
```

No incidents to date (2026-09-17).
