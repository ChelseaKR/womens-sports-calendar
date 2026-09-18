# 0004. Which portfolio standards and controls do not apply here

Status: Accepted
Date: 2026-09-17
Deciders: Chelsea Kelly-Reif

## Context

CODE-QUALITY-STANDARD §8 (CQ-45) requires an ADR for declaring a standard
N/A. The portfolio registry (`applicability.yml`) marks every standard
`applies` for this repository except AI Evaluation. Several standards also
name controls that do not fit a static site built by a nightly batch job.
Each of those needs a written reason, never a silent skip.

## Decision

- **AI-EVALUATION-STANDARD: N/A.** There is no LLM, prompt, retrieval or
  model component. The pipeline reads the Ticketmaster Discovery API and
  renders it deterministically. The first LLM dependency reverses this
  (AIEV-01).
- **CI stage 8 (responsible gates): N/A.** There's no consent gate, no
  no-outing or identity-inference guard, and no grounding guard, because
  none of those surfaces exists. This product's own guarantees (a failed or
  empty fetch never publishes; absence is never shown as a value) are
  tested in stage 4.
- **PERFORMANCE-STANDARD PERF-01 (k6): N/A.** GitHub Pages serves static
  files; no server route of ours runs, so a p95 would measure GitHub's CDN.
  Lighthouse budgets apply (PERF-02, PERF-03).
- **OBSERVABILITY-STANDARD OTel traces, metrics, SLOs, `/livez`, `/readyz`:
  N/A.** No service of ours runs at request time. The site is Tier B and
  the pipeline Tier C. The PII-in-logs gate (OBS-11) still applies and is
  met.
- **DATA-GOVERNANCE-STANDARD §3 backup/DR: N/A.** There's no persistent
  data store. Every night rebuilds everything from the source and the
  repository. RPO and RTO are still stated in `docs/ROADMAP.md`.
- **CITATION.cff: N/A.** This is a commercial consumer site with no
  scholarly or civic-reuse intent (DOCUMENTATION-STANDARD §4).
- **Container scanning (SEC-28): N/A.** There's no Dockerfile.

## Consequences

The README conformance table points here for each N/A. Any of these
reverses the matching line: adding an LLM, a server route, a persistent
store, a container, or research use.
