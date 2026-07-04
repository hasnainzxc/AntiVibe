# Feature: GitHub OAuth App

**Purpose:** OAuth App flow for repo read access + token store w/ encryption + scope mgmt.
**Wave:** 5  **Owner task:** 34  **Status:** pending

## Public API
- `GET /api/github/connect` → redirect to github.com/login/oauth/authorize
- `GET /api/github/callback?code=...` → exchange code → store encrypted token
- `DELETE /api/github/disconnect` → revoke GitHub token + delete row

## Internal flow
1. Token stored in `oauth_tokens.access_token_encrypted` (AES-256-GCM via Supabase Vault or local encrypt by SUPABASE_SERVICE_ROLE_KEY as secret)
2. Scope: `repo` (private repos) + `pull_requests:write` (auto-PR)
3. Disconnect: call `DELETE /applications/{client_id}/grant` to revoke; delete row

## Acceptance criteria
- [ ] User can connect → see their repos → disconnect
- [ ] Token encrypted at rest
- [ ] No token leaked in dashboard XSS

## Test plan
```
Scenario: Connect flow
  Steps: dashboard → /api/github/connect → external OAuth → callback → /api/github/repos returns repos list
Scenario: Disconnect revokes token at GitHub
  Steps: disconnect → GitHub response 204 → try /api/repos → 401
```

## Cross-references
- [see api-spec.md#post-apigithubconnect]
- [see security-threat-model.md#elevation-of-privilege]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |