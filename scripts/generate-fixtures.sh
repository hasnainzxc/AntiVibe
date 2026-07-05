#!/usr/bin/env bash
set -euo pipefail

FIXTURES_DIR="$(cd "$(dirname "$0")/.." && pwd)/fixtures"

echo "Creating fixture repos..."

for repo in vuln-nextjs vuln-express clean-app; do
  repo_path="$FIXTURES_DIR/$repo"
  echo "  -> $repo"

  cd "$repo_path"

  if [ -d ".git" ]; then
    rm -rf .git
  fi

  git init --quiet
  git add -A
  git commit -m "chore: initial scaffold for $repo" --quiet

  echo "  -> $repo: committed $(git rev-list --count HEAD) commit(s)"
done

echo ""
echo "3 fixture repos created in fixtures/"
echo ""
echo "Summary:"
echo "  vuln-nextjs/  — Next.js app with IDOR, missing auth, hardcoded AWS keys"
echo "  vuln-express/ — Express app with IDOR, no rate limit, hardcoded JWT, Stripe key"
echo "  clean-app/    — Clean Next.js app with auth middleware, no secrets"
