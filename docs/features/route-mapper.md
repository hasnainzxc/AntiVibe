# Feature: Route Mapper

**Purpose:** Per-stack route index built on AstParser output — flat list w/ auth_required flag for each route, used by Tier 3 fuzz agent.
**Wave:** 3  **Owner task:** 19  **Status:** pending

## Public API
```python
@dataclass
class RouteIndexEntry:
    path: str                     # e.g. /api/users/:id
    methods: list[HttpMethod]
    params: dict[str, ParameterShape]
    body_shape: SchemaShape | None
    auth_required: bool           # inferred from code (NextAuth getSession / Clerk auth() / @app.route guarded/etc)
    file_path: str
    line: int

class RouteMapper:
    def build_index(self, ast_result: AstResult, *, stack: Stack, auth_stack: AuthStack) -> list[RouteIndexEntry]: ...
```

## Internal flow
1. Receive AstParser output (Task 11): list[RouteShape], imports dict
2. For each route, infer auth_required by:
   - NextAuth: route file imports `getServerSession` and uses it in the handler
   - Clerk: route file calls `auth()` from `@clerk/nextjs`
   - Firebase: `requireAuth` HOF applied
   - Supabase: `await supabase.auth.getUser()` present
   - Custom: `JWT_SECRET` env read INSIDE handler
3. If `auth_required=false` and route serves sensitive data → emit "info" finding (open API surface)
4. Normalize param placeholders per stack to `:param` convention (Next.js `[id]` → `:id`)

## Inputs
- AstResult (Task 11): routes, env_refs, imports
- Stack enum
- AuthStack enum (from Tier 1 detection)

## Outputs
- list[RouteIndexEntry] for Tier 3 consumption

## Acceptance criteria
- [ ] ≥95% route match against fixture truth-set per stack
- [ ] `auth_required` flag accurate for NextAuth/Clerk/Firebase/Supabase/custom
- [ ] Open API surfaces (false auth_required on sensitive paths) flagged as info-level finding

## Test plan
```
Scenario: NextAuth-protected route marked auth_required=true
  Steps: route-map fixture w/ route `app/api/users/route.ts` using getServerSession
  Expected: entry.auth_required = true
Scenario: Open route detected
  Steps: route-map fixture w/ route no auth call
  Expected: entry.auth_required = false + 1 info finding "open api surface"
```

## Cross-references
- [see system-design.md#llm-dual-model-contract]
- [see system-design.md#no-stop-pivot-spec]
- [see sandbox-isolation.md#jwt-forge]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |