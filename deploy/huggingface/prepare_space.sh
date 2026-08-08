#!/usr/bin/env bash
# Assemble a Hugging Face Space commit without touching the GitHub working tree.
# See prepare_space.ps1 for why a separate README is staged.
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 https://huggingface.co/spaces/<user>/youhuo" >&2
  exit 2
fi
SPACE_REPO="$1"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
STAGE="$(mktemp -d)/youhuo-space"
mkdir -p "$STAGE"
echo "staging in $STAGE"

for item in backend xiaoyi Dockerfile .dockerignore \
            requirements.txt requirements.lock.txt LICENSE THIRD_PARTY_NOTICES.md; do
  [ -e "$ROOT/$item" ] || { echo "missing $item" >&2; exit 1; }
  cp -R "$ROOT/$item" "$STAGE/$item"
done

find "$STAGE" -type d \( -name __pycache__ -o -name .pytest_cache -o -name tests -o -name data \) \
  -prune -exec rm -rf {} + 2>/dev/null || true

cp "$HERE/README.md" "$STAGE/README.md"

cd "$STAGE"
git init >/dev/null   # --initial-branch needs git >= 2.28; push names the branch
git add -A
git -c user.email=space@youhuo.local -c user.name=youhuo \
    commit -m "YouHuo online demo (login-free, per-visitor sandbox)" >/dev/null
git remote add space "$SPACE_REPO"

echo
echo "ready. now run:"
echo "  cd $STAGE"
echo "  git push space HEAD:main --force"
echo
echo "username = your Hugging Face name; password = a Write access token."
