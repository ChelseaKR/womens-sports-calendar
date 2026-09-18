# 0000. Record architecture decisions

Status: Accepted
Date: 2026-09-17
Deciders: Chelsea Kelly-Reif

## Context

DOCUMENTATION-STANDARD §3 (DOC-04, DOC-05) asks for an ADR log in
`docs/adr/`: numbered, MADR-shaped, append-only. This repository already
keeps a decision log, `docs/DECISIONS.md` (entries 0001–0010, 2026-09-13 to
2026-09-16), and code comments cite it as "DECISIONS 00NN". Moving those
entries would break every such reference and rewrite history that is
already correct.

## Decision

- New architecturally significant decisions are recorded as ADR files,
  `docs/adr/NNNN-kebab-title.md`, in MADR shape (Status, Date, Deciders,
  Context, Decision, Consequences), numbered from 0001 in their own
  sequence. They are cited as "ADR NNNN".
- `docs/DECISIONS.md` stays where it is as the pre-ADR record, cited as
  "DECISIONS NNNN". It is not migrated and new decisions are not appended
  to it.
- An `Accepted` ADR is never edited to change its meaning. A later ADR that
  changes course sets the earlier one's status to `Superseded by NNNN` and
  says why.
- A PR that changes a guardrail (the absence discipline, the
  "a failed fetch never publishes an empty calendar" rule, a `permissions:`
  block, a coverage or accessibility threshold) or declares a standard N/A
  links an ADR.

## Consequences

Decisions made from here on are diffable and reviewable in one place. Two
number sequences exist ("DECISIONS 0006", "ADR 0001"); the prefix always
says which one is meant.
