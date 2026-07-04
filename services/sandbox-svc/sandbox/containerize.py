"""Per-stack Dockerfile generator for sandbox Fly Machines.

Architecture
------------
This module is the only place that knows the "shape" of a runnable
AntiVibe sandbox image. It maps a detected `scanner.detect_stack.Stack`
value to a Dockerfile template and writes it into a *scratch* directory
that is separate from the user's repo (so the user's repo is never
mutated by the scanner — important for trust, caching, and reproducibility).

Design rationale
----------------
- Pure-function templates: each template is a `Path -> str` function.
  This lets tests call them without touching the filesystem, and lets
  callers swap templates via the `TEMPLATES` registry without subclassing.
- Whitelist-driven: only the 6 whitelisted stacks are supported. Anything
  else raises `ValueError` (not `NotImplementedError`) because from the
  caller's perspective "we explicitly do not support this stack" is a
  contract, not a missing feature.
- Multi-stage builds where it matters (Next.js) to keep the final image
  free of build-time devDeps. Single-stage for the rest to keep the
  templates small and reviewable.
- `corepack enable && pnpm install --frozen-lockfile --ignore-scripts`
  is the universal Node install idiom: `--frozen-lockfile` is a
  supply-chain guard (refuses to update pnpm-lock.yaml), and
  `--ignore-scripts` blocks arbitrary `postinstall` execution from
  third-party packages during image build.

Dependency map
--------------
- Reads from: `scanner.detect_stack.Stack` (enum of detected stacks).
- Writes to: caller-supplied scratch directory. Never writes to the
  user repo. The caller (sandbox spin-up flow) is responsible for
  staging the Dockerfile alongside the cloned repo and handing the
  resulting path to the Fly build pipeline.

Testing
-------
- `tests/sandbox/test_containerize.py` exercises each of the 6
  templates, the registry shape, the unsupported-stack rejection path,
  and the write-to-scratch contract.
- No network. No subprocess. No filesystem side effects beyond the
  caller-supplied output directory.
"""

from pathlib import Path

from scanner.detect_stack import Stack

UNSUPPORTED_STACK_ERROR = "cant containerize (stack not in whitelist)"

# Per-stack Dockerfile templates.
#
# Port conventions — these are baked into the runtime image and into the
# scanner's health probe. Changing them here is a breaking change to the
# scanner contract:
#   nextjs     -> 3000   (Next.js standalone server)
#   express    -> 8000   (Node http server)
#   firebase   -> 4000 (emulator UI), 5001 (functions), 8080 (firestore), 9099 (auth)
#   fastapi    -> 8000   (uvicorn)
#   flask      -> 5000   (gunicorn)
#   sveltekit  -> 4173   (vite preview)


def _dockerfile_nextjs(repo_root: Path) -> str:
    """Next.js Dockerfile — multi-stage build for `.next/standalone`.

    Stage 1 (`builder`) runs `pnpm build` with all devDeps; stage 2
    copies only the standalone output, `.next/static`, and `public/`.
    Result: ~150 MB image instead of ~800 MB.

    `NEXT_TELEMETRY_DISABLED=1` suppresses Next.js' anonymous build
    telemetry; the scanner has no business phoning home from a sandbox
    image.
    """
    return '''FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json pnpm-lock.yaml* .npmrc* ./
RUN corepack enable && pnpm install --frozen-lockfile --ignore-scripts
COPY . .
RUN pnpm build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
'''


def _dockerfile_express(repo_root: Path) -> str:
    """Express Dockerfile — single-stage, assumes `dist/index.js` is built.

    `pnpm build 2>/dev/null || true` is intentional: many Express apps
    have a `build` script that just type-checks or is a no-op. We don't
    want image build to fail for a non-fatal script; the scanner has
    already verified the entrypoint shape during stack detection.
    """
    return '''FROM node:20-alpine
WORKDIR /app
COPY package.json pnpm-lock.yaml* .npmrc* ./
RUN corepack enable && pnpm install --frozen-lockfile --ignore-scripts
COPY . .
RUN pnpm build 2>/dev/null || true
EXPOSE 8000
CMD ["node", "dist/index.js"]
'''


def _dockerfile_firebase(repo_root: Path) -> str:
    """Firebase Dockerfile — runs the emulator suite (firestore + auth + functions).

    Uses the global `firebase-tools` package (latest at build time).
    Exposes all four emulator ports (4000=UI, 5001=functions, 8080=firestore,
    9099=auth) so the scanner can probe any surface without rebuilding.

    `--project antivibe-sandbox` pins the project ID for emulator mode;
    emulators don't talk to real GCP, but a stable project ID keeps
    rules and indexes consistent across runs.
    """
    return '''FROM node:20-alpine
WORKDIR /app
RUN npm install -g firebase-tools@latest
COPY package.json pnpm-lock.yaml* .npmrc* ./
RUN corepack enable && pnpm install --frozen-lockfile --ignore-scripts
COPY . .
EXPOSE 4000 5001 8080 9099
CMD ["firebase", "emulators:start", "--only", "firestore,auth,functions", "--project", "antivibe-sandbox"]
'''


def _dockerfile_fastapi(repo_root: Path) -> str:
    """FastAPI Dockerfile — uvicorn on 0.0.0.0:8000.

    `pip install --no-cache-dir` keeps the image small; FastAPI/uvicorn
    dependency resolution is deterministic enough not to need wheels
    cached in the layer.
    """
    return '''FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
'''


def _dockerfile_flask(repo_root: Path) -> str:
    """Flask Dockerfile — gunicorn with 2 sync workers.

    Two workers is the minimum to exercise concurrency-dependent
    behavior in scans (race conditions, session locking) without
    spiking memory in a 512 MB Fly Machine.
    """
    return '''FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "2"]
'''


def _dockerfile_sveltekit(repo_root: Path) -> str:
    """SvelteKit Dockerfile — `vite preview` on 4173.

    Uses the production preview server (not dev) so the scanner sees
    real bundle behavior. `--host 0.0.0.0` is required for Fly's
    internal network to reach the container.
    """
    return '''FROM node:20-alpine
WORKDIR /app
COPY package.json pnpm-lock.yaml* .npmrc* ./
RUN corepack enable && pnpm install --frozen-lockfile --ignore-scripts
COPY . .
RUN pnpm build
EXPOSE 4173
CMD ["pnpm", "preview", "--", "--host", "0.0.0.0", "--port", "4173"]
'''


# Stack -> template function. Adding a new stack means: write a template
# function, add an entry here, and add the new `Stack` variant upstream.
# The tests assert `len(TEMPLATES) == 6` so missing entries are loud.
TEMPLATES: dict[Stack, "callable"] = {
    Stack.NEXTJS: _dockerfile_nextjs,
    Stack.EXPRESS: _dockerfile_express,
    Stack.FIREBASE: _dockerfile_firebase,
    Stack.FASTAPI: _dockerfile_fastapi,
    Stack.FLASK: _dockerfile_flask,
    Stack.SVELTEKIT: _dockerfile_sveltekit,
}


def generate_dockerfile(stack: Stack, repo_root: Path) -> str:
    """Generate a Dockerfile for the given stack and repo.

    Args:
        stack: Detected stack enum from `scanner.detect_stack.Stack`.
        repo_root: Path to the cloned repo. Currently unused by all
            templates (kept for future template customization hooks
            like env injection) but must be supplied to match the
            containerizer signature used by the spin-up orchestrator.

    Returns:
        Dockerfile content as a single string, ready to be written
        to disk or passed to a container builder.

    Raises:
        ValueError: if `stack` is not in the whitelist. The error
            message is the union of the standard
            `UNSUPPORTED_STACK_ERROR` prefix and the rejected value
            so callers can both match the prefix and surface the
            value in their own logs.
    """
    template_fn = TEMPLATES.get(stack)
    if template_fn is None:
        raise ValueError(f"{UNSUPPORTED_STACK_ERROR}: {stack}")
    return template_fn(repo_root)


def write_dockerfile(stack: Stack, repo_root: Path, output_dir: Path) -> Path:
    """Write `Dockerfile.antivibe` to `output_dir` (scratch, NOT user repo).

    Always uses the literal filename `Dockerfile.antivibe` (not
    `Dockerfile`) to make it obvious in the build context that this
    file came from the scanner, not the user's repo.

    Args:
        stack: Detected stack enum.
        repo_root: Path to the cloned repo (passed through to the
            template; currently informational).
        output_dir: Scratch directory. Created recursively if missing.

    Returns:
        Absolute `Path` to the written Dockerfile.

    Raises:
        ValueError: if `stack` is not whitelisted (propagated from
            `generate_dockerfile`).
        OSError: if `output_dir` cannot be created or the file cannot
            be written (e.g. permission denied, disk full).
    """
    content = generate_dockerfile(stack, repo_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    dockerfile_path = output_dir / "Dockerfile.antivibe"
    dockerfile_path.write_text(content)
    return dockerfile_path
