# Definition of Done

This repository uses the canonical delivery gate in
`docs/standards/QUALITY-AND-METRICS-STANDARD.md` (vendored v2.0.0). A change is
done only when:

1. `make verify` passes, and so does every required check on the final
   reviewed head, without bypass or ignored failure. The required checks are
   `verify`, `zizmor`, `workflow-policy`, `gitleaks`, `semgrep` and
   `osv-scanner`.
2. Every applicable REVIEW-GATE has an accountable human disposition and a
   current, dated artifact. That includes an ADR for a guardrail or threshold
   change, the threat-model note for new external surface, and the
   accessibility review for a new interactive component.
3. The PR records the diff, the risk boundaries it touches, findings,
   remediation, residual risks and how to roll back. For this site, rollback
   is re-running `pages.yml` on the previous good commit.
4. Documentation, the README conformance table, `CHANGELOG.md`, tests and
   data cards agree with the change.
5. A new data source has passed "licence before bytes" (`docs/DECISIONS.md`
   0003) and has a data card in `docs/data/` before its first fetch.

While this is a one-maintainer project, "done" is the maintainer's own
recorded decision, not an independent review (`CODE-QUALITY-STANDARD.md`
§7.1). Nothing here claims otherwise.
