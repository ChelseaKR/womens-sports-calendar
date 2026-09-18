## What and why

<!-- One concern. Link the issue it closes or advances. -->

## Definition of Done (DEFINITION_OF_DONE.md)

- [ ] `make verify` is green locally and every required check is green on this head
- [ ] The quality attribute this changes is named (ISO 25010: e.g. reliability, security, interaction capability)
- [ ] Tests cover the change; if a check was added, a planted failure shows it can fail
- [ ] Guardrail, threshold, `permissions:` or N/A change → ADR in `docs/adr/`
- [ ] New data source → licence read and quoted, data card in `docs/data/`
- [ ] New interactive component → keyboard/screen-reader review noted (ACCESSIBILITY-STANDARD §2)
- [ ] Docs, README conformance table and `CHANGELOG.md` (Unreleased) updated
- [ ] Rollback: how to undo this if it breaks the live site

## Risk and residuals

<!-- What could go wrong, what is accepted, what is left open (with issue links). -->
