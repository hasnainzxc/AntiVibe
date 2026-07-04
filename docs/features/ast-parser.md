# Feature: AST Parser

**Purpose:** Per-stack AST parser extracting routes, env refs, imports from cloned repo source code.
**Wave:** 2  **Owner task:** 11  **Status:** pending

## Public API
```python
@dataclass
class RouteShape:
    path: str; methods: list[str]; params: dict[str, ParameterShape]; body_shape: SchemaShape | None; auth_required: bool | None

@dataclass
class EnvRef:
    name: str; file: str; line: int; fallback: str | None

@dataclass
class DependencyRef:
    name: str; version: str | None; type: str  # 'prod'|'dev'|'peer'

class AstParser:  # abstract
    def extract_routes(self) -> list[RouteShape]: ...
    def find_env_refs(self) -> list[EnvRef]: ...
    def extract_imports(self) -> dict[str, DependencyRef]: ...

# Per-stack impls:
class NextjsParser(AstParser): ...
class ExpressParser(AstParser): ...
class FastApiParser(AstParser): ...
class FlaskParser(AstParser): ...
class SvelteKitParser(AstParser): ...
class FirebaseParser(AstParser): ...
```

## Internal flow
1. Walk conventional files per stack (Next.js: `app/**/{route.ts,page.tsx}`, etc.; FastAPI: `app.py` w/ `@app.METHOD(/path)`; Flask: `@app.route`)
2. Use SWC-wasm for TS, Python `ast` module for Py
3. Cache results keyed by file mtime
4. Resilience: per-file exceptions logged as `ast.warn`, parser continues other files

## Inputs
- repo root path
- stack enum (from task 10)

## Outputs
- list[RouteShape]
- list[EnvRef]
- dict[str, DependencyRef]

## Acceptance criteria
- [ ] All 6-stack happy paths pass
- [ ] Per fixture, route count matches hand-counted ±1
- [ ] New adapters registerable w/o core changes

## Test plan
```
Scenario: Next.js routes extracted
  Steps: python -m scanner.ast_parser /fixture/nextjs --stack nextjs
  Expected: 2 routes `[{path:"/api/users",methods:["GET"]},{path:"/api/users/:id",methods:["GET","PATCH"]}]`
Scenario: Resilient parse ignores broken file
  Steps: parser on fixture w/ 1 syntactically broken file
  Expected: warns + still returns routes from valid files
```

## Cross-references
- [see system-design.md#llm-dual-model-contract] (route map input)
- [see architecture.md#tier-pipeline-diagram]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |