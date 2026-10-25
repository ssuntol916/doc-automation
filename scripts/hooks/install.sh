#!/usr/bin/env bash
# Install only this repository's versioned Git hooks.
set -euo pipefail

TASK_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${TASK_REPO_ROOT}"
if [ "$(git rev-parse --show-toplevel)" != "${TASK_REPO_ROOT}" ]; then
  printf 'error: 현재 프로젝트 루트에서 Git 저장소를 초기화해야 합니다.\n' >&2
  exit 1
fi
if [ ! -x .githooks/commit-msg ]; then
  printf 'error: 실행 가능한 .githooks/commit-msg 파일이 필요합니다.\n' >&2
  exit 1
fi
git config --local core.hooksPath .githooks
printf '커밋 메시지 훅 설치 완료: %s/.githooks\n' "${TASK_REPO_ROOT}"
