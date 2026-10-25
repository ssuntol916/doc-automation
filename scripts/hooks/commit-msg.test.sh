#!/usr/bin/env bash
# commit-msg 훅의 판정을 고정한다.
#
# 훅은 사람이 커밋할 때만 도는 자리라 조용히 망가져도 한동안 드러나지 않는다. 그래서
# 통과해야 하는 메시지와 막아야 하는 메시지를 여기에 함께 적어 둔다.
#
#   bash scripts/hooks/commit-msg.test.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOOK="${REPO_ROOT}/.githooks/commit-msg"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT

passed=0
failed=0

run_hook() {
  printf '%s\n' "$1" > "${WORKDIR}/message"
  "${HOOK}" "${WORKDIR}/message" >"${WORKDIR}/out" 2>&1
}

expect_ok() {
  local name="$1" message="$2"
  if run_hook "${message}"; then
    printf '  ok    %s\n' "${name}"
    passed=$((passed + 1))
  else
    printf '  FAIL  %s — 통과해야 하는데 막혔습니다\n' "${name}"
    sed 's/^/          /' "${WORKDIR}/out"
    failed=$((failed + 1))
  fi
}

# 거절은 **이유와 함께** 나와야 한다. 종료 코드만 보면 훅이 shell 오류로 죽은 것도 거절로
# 세어 버린다. 실제로 그렇게 통과한 시험이 있었고, 사람은 커밋이 왜 막혔는지 모른 채 남았다.
expect_reject() {
  local name="$1" message="$2"
  if run_hook "${message}"; then
    printf '  FAIL  %s — 막아야 하는데 통과했습니다\n' "${name}"
    failed=$((failed + 1))
  elif ! grep -q "커밋 메시지가" "${WORKDIR}/out"; then
    printf '  FAIL  %s — 거절 사유 없이 죽었습니다\n' "${name}"
    sed 's/^/          /' "${WORKDIR}/out"
    failed=$((failed + 1))
  else
    printf '  ok    %s\n' "${name}"
    passed=$((passed + 1))
  fi
}

VALID='feat(projects): 프로젝트 목록 화면과 상태 거르개

- taxonomy leaf에 붙는 프로젝트 목록 표와 상태·담당자 거르개
- 회사 범위 밖 행을 막는 RLS 정책과 그 회귀 시험'

printf '통과해야 하는 메시지\n'
expect_ok "표준 형식" "${VALID}"
expect_ok "scope 없음" 'docs: 커밋 규칙 문서화

- AGENTS.md 「커밋 규칙」 절과 예시
- 훅 설치 안내 한 줄'
expect_ok "scope에 / . - 포함" 'fix(lib/navigation.routes-v2): 중복 leaf id 판정 누락 보완

- 같은 href를 가진 leaf 둘을 등록 시점에 막는 검사
- 그 경계를 고정하는 시험'
expect_ok "bullet 5개(권고 초과는 알림만)" 'chore(deps): Core 릴리스 자산 0.0.38 채택

- 패키지 셋 file 의존과 lockfile 정합
- 릴리스 자산 검증 스크립트 이관
- 자산 디렉터리 추적 제외
- 조립 진입점 정리
- 문서 갱신'

printf '\n막아야 하는 메시지\n'
expect_reject "빈 메시지" ''
expect_reject "허용하지 않는 type" 'update(projects): 프로젝트 목록 화면

- 목록 표
- 거르개'
expect_reject "type 없음" '프로젝트 목록 화면 추가

- 목록 표
- 거르개'
expect_reject "대문자 scope" 'feat(Projects): 프로젝트 목록 화면

- 목록 표
- 거르개'
expect_reject "본문 없음" 'feat(projects): 프로젝트 목록 화면'
expect_reject "제목 다음 줄이 비어 있지 않음" 'feat(projects): 프로젝트 목록 화면
- 목록 표
- 거르개'
expect_reject "bullet 1개" 'feat(projects): 프로젝트 목록 화면

- 목록 표'
expect_reject "bullet이 아닌 본문 줄" 'feat(projects): 프로젝트 목록 화면

- 목록 표
거르개도 함께'
expect_reject "제목이 다로 끝남" 'feat(projects): 프로젝트 목록 화면을 추가한다

- 목록 표
- 거르개'
expect_reject "bullet이 다로 끝남" 'feat(projects): 프로젝트 목록 화면

- 목록 표를 추가한다
- 거르개'
expect_reject "제목이 마침표로 끝남" 'feat(projects): 프로젝트 목록 화면.

- 목록 표
- 거르개'
expect_reject "Git 기본 병합 제목" 'Merge branch dev into feature/projects

- 병합
- 충돌 없음'
expect_reject "fixup! 메시지" 'fixup! feat(projects): 프로젝트 목록 화면

- 목록 표
- 거르개'
expect_reject "Co-Authored-By 포함" 'feat(projects): 프로젝트 목록 화면

- 목록 표
- 거르개

Co-Authored-By: Someone <someone@example.com>'
expect_reject "생성 도구 표기" 'feat(projects): 프로젝트 목록 화면

- 목록 표
- 거르개

Generated with some tool'
expect_reject "병합 아닌데 merge type" 'merge(projects): 프로젝트 목록 화면 통합

- 목록 표
- 거르개'

printf '\n통과 %d건, 실패 %d건\n' "${passed}" "${failed}"
[ "${failed}" -eq 0 ] || exit 1
