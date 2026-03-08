# delta 記録テンプレート

正本は Markdown（`docs/delta/*.md`）で管理し、JSON/YAML の副管理を要求しない。

## Delta ID
- DR-YYYYMMDD-<short-name>

## Delta Type
- FEATURE / REPAIR / DESIGN / REVIEW / DOCS-SYNC / OPS

## Step 1: delta-request
- purpose:
- In Scope:
- Out of Scope:
- Acceptance Criteria:
- constraints:
- review gate required: Yes / No
- review checklist: `docs/delta/REVIEW_CHECKLIST.md`

## Step 2: delta-apply
- changed files:
- applied AC:
- code split check:
  - file over 500 lines: Yes / No
  - file over 800 lines: Yes / No
  - file over 1000 lines: Yes / No
- status: APPLIED / BLOCKED

## Step 3: delta-verify
- verify profile:
  - static check:
  - targeted unit:
  - targeted integration / E2E:
  - delta validator:
- review delta outcome:
  - pass:
  - follow-up delta seeds:
- AC result table:
- scope deviation:
- review findings:
  - layer integrity:
  - docs sync:
  - data size:
  - code split health:
- overall: PASS / FAIL

## Step 4: delta-archive
- verify result: PASS
- review gate: PASSED / NOT REQUIRED
- archive status: archived
- unresolved items:
- follow-up delta seeds:

## Canonical Sync
- synced docs:
  - concept:
  - spec:
  - architecture:
  - plan:

## Validation Command
- `node scripts/validate_delta_links.js --dir .`
- `node scripts/check_code_size.js --dir .`
