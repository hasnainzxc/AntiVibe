# Feature: Webhook Handler

**Purpose:** GitHub push-triggered scan + HMAC-SHA256 signature verify + idempotency via webhook_deliveries.event_id.
**Wave:** 5  **Owner task:** 35  **Status:** pending

## Public API
- `POST /api/webhooks/github` — verify `x-hub-signature-256` → unmarshal → re-route to Tier 1

## Internal flow
1. Constant-time compare `HMAC-SHA256(body, GITHUB_WEBHOOK_SECRET)` vs header
2. Check `x-github-delivery` not already in `webhook_deliveries.event_id` (idempotency)
3. Extract `repository.clone_url` + `ref`
4. Call `POST /api/scan {repo_url, branch}` on behalf of user (requires connected OAuth, mapped via repo → user via `oauth_tokens`)
5. Return 200 always (don't leak error to GitHub)
6. Insert into `webhook_deliveries` row

## Acceptance criteria
- [ ] Valid signature triggers scan; invalid returns 200 w/o triggering
- [ ] Idempotent (same event_id twice = no second scan)

## Test plan
```
Scenario: Valid push triggers scan
Scenario: Fake signature ignored
Scenario: Duplicate event_id skipped
```

## Cross-references
- [see api-spec.md#post-apiwebhooksgithub]
- [see security-threat-model.md#spoofing]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |