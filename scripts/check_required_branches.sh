#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1090
source "${ROOT}/config/site.env"

check() {
  local repo="$1" required="$2" label="$3"
  if [[ ! -d "${repo}/.git" ]]; then
    echo "MISSING ${label} repository: ${repo}"
    return 1
  fi
  local branch
  branch="$(git -C "${repo}" branch --show-current)"
  if [[ "${branch}" == "${required}" ]]; then
    echo "OK      ${label}: ${branch}"
  else
    echo "WARNING ${label}: current=${branch:-DETACHED}, required=${required}"
  fi
}

check "${WORKFLOW_REPO}" "feature/mpas-workflow-foundation" "workflow"
check "${BMATRIX_REPO}" "feature/nmc-campaign-manifest" "bmatrix"

cat <<'EOF'
Expected preparation:
  git -C "$WORKFLOW_REPO" fetch origin feature/mpas-workflow-foundation
  git -C "$WORKFLOW_REPO" switch feature/mpas-workflow-foundation
  git -C "$BMATRIX_REPO" fetch origin feature/nmc-campaign-manifest
  git -C "$BMATRIX_REPO" switch feature/nmc-campaign-manifest
EOF
