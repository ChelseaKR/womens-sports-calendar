# Rulesets

`main.json` is the proposed repository-owned `protect-main` ruleset
(CI-CD-STANDARD §5). It is committed so the merge policy is reviewable in the
tree; committing it does not apply it. The owner applies it (commands in the
PR that added this file) once every context below reports on `main`.

| Field | Value | Why |
|---|---|---|
| `bypass_actors` | the repository-admin role (`actor_id` 5), `bypass_mode: always` | CICD-15: the accountable maintainer keeps a break-glass path for a wedged required check. An empty list is a lockout, not a stricter setting. Every bypassed merge is recorded in its PR. |
| `required_approving_review_count` | 0 | One active maintainer; GitHub cannot count a self-approval (CI-CD-STANDARD §5.1). This is only conformant alongside a current solo-maintainer declaration and the `solo-governance` check, which are not in this repository yet (tracked as a CI/CD gap). |
| `require_code_owner_review` | false | Same reason; `.github/CODEOWNERS` still routes review requests. |
| `dismiss_stale_reviews_on_push` | true | CICD-14. |
| required checks | `verify` (ci.yml), `zizmor` + `workflow-policy` (workflow-lint.yml), `gitleaks` + `semgrep` + `osv-scanner` (security.yml) | CICD-13, strict (branch must be up to date). `integration_id` 15368 is GitHub Actions, so no other app can post a passing status under these names. |
| `required_signatures`, `required_linear_history`, `non_fast_forward`, `deletion` | on | CQ-41, CICD-16. Merges through the GitHub UI are signed by GitHub. |
