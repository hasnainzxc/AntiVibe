"""Per-stack Dockerfile generator for sandbox Fly Machines.

Generates Dockerfile.antivibe in a scratch directory (never in user repo).
Supports 6 stacks: nextjs, express, firebase, fastapi, flask, sveltekit.
"""

from pathlib import Path

from scanner.detect_stack import Stack

UNSUPPORTED_STACK_ERROR = "cant containerize (stack not in whitelist)"

# Per-stack Dockerfile templates
# Each template is a function that returns Dockerfile content as string
# Templates use port conventions:
#   nextjs     -> 3000
#   express    -> 8000
#   firebase   -> 4000 (emulator suite), 5001 (functions)
#   fastapi    -> 8000
#   flask      -> 5000
#   sveltekit  -> 4173


def _dockerfile_nextjs(repo_root: Path) -> str:
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
    return '''FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
'''


def _dockerfile_flask(repo_root: Path) -> str:
    return '''FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "2"]
'''


def _dockerfile_sveltekit(repo_root: Path) -> str:
    return '''FROM node:20-alpine
WORKDIR /app
COPY package.json pnpm-lock.yaml* .npmrc* ./
RUN corepack enable && pnpm install --frozen-lockfile --ignore-scripts
COPY . .
RUN pnpm build
EXPOSE 4173
CMD ["pnpm", "preview", "--", "--host", "0.0.0.0", "--port", "4173"]
'''


# Registry
TEMPLATES = {
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
        stack: Detected stack enum from Task 10
        repo_root: Path to cloned repo

    Returns:
        Dockerfile content as string

    Raises:
        ValueError: if stack is not in the whitelist
    """
    template_fn = TEMPLATES.get(stack)
    if template_fn is None:
        raise ValueError(f"{UNSUPPORTED_STACK_ERROR}: {stack}")
    return template_fn(repo_root)


def write_dockerfile(stack: Stack, repo_root: Path, output_dir: Path) -> Path:
    """Write Dockerfile.antivibe to output_dir (scratch, NOT user repo).

    Returns path to written Dockerfile.
    """
    content = generate_dockerfile(stack, repo_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    dockerfile_path = output_dir / "Dockerfile.antivibe"
    dockerfile_path.write_text(content)
    return dockerfile_path
