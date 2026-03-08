---
name: delta-verify
description: 「delta verify」「差分の検証をして」「request通りか確認して」などの依頼で使用。delta-requestとdelta-applyの整合性を検証し、逸脱や不良を後工程へ流さない。
---

# Delta Verify

## 目的
- 作成済み差分が request を満たすか判定する。
- 逸脱・不整合・不良を検出して止める。

## 入力
- delta-request（Delta ID, AC, In/Out Scope）
- delta-apply（変更ファイル, AC対応説明）
- 実際の差分/成果物

## 厳守ルール（逸脱禁止）
- 判定基準は request の AC と制約のみを使う。
- 「あった方がよい改善」を合否基準に混ぜない。
- Out of Scope の変更は失敗として報告する。
- 根拠のない推測で合格にしない。
- 判定不能（証跡不足）は PASS にせず FAIL とする。
- `review gate required: Yes` の delta では、AC 判定に加えてレビュー観点を別枠で評価する。
- `Delta Type = REVIEW` の場合は `docs/delta/REVIEW_CHECKLIST.md` を使って点検する。

## 検証フロー
1. 標準 verify プロファイルを確定する（static check / targeted unit / targeted integration or E2E / delta validator）。
2. AC ごとに証跡を確認する。
3. In Scope / Out of Scope の逸脱を確認する。
4. 変更前後の整合性と回帰リスクを確認する。
5. review gate が必要な場合は、レイヤー構造、文書同期、データ肥大、コード分割健全性を確認する。
6. コード分割健全性では、通常のソースコードについて 500 行超はレビュー済みか、800 行超は分割済みか、1000 行超は例外として妥当かを確認する。
7. REVIEW delta で問題があれば、必要な follow-up delta seeds を明示する。
8. PASS/FAIL を決定し、FAIL は最小修正指示を返す。

## 出力テンプレート（固定）
```markdown
# delta-verify

## Delta ID
- （requestと同一）

## Verify Profile
- static check:
- targeted unit:
- targeted integration / E2E:
- delta validator:

## 検証結果（AC単位）
| AC | 結果(PASS/FAIL) | 根拠 |
|---|---|---|
| AC-01 | PASS | |
| AC-02 | FAIL | |

## スコープ逸脱チェック
- Out of Scope 変更の有無: Yes/No
- 逸脱内容:

## 不整合/回帰リスク
- R-01:

## Review Gate
- required: Yes/No
- checklist: `docs/delta/REVIEW_CHECKLIST.md`
- layer integrity: PASS/FAIL/NOT CHECKED
- docs sync: PASS/FAIL/NOT CHECKED
- data size: PASS/FAIL/NOT CHECKED
- code split health: PASS/FAIL/NOT CHECKED
- file-size threshold: PASS/FAIL/NOT CHECKED

## Review Delta Outcome
- pass: Yes/No
- follow-up delta seeds:

## 判定
- Overall: PASS / FAIL

## FAIL時の最小修正指示
- Fix-01:
```

## 品質ゲート（出力前チェック）
- 標準 verify プロファイルの実施有無が書かれている。
- 全 AC が判定されている。
- 判定ごとに根拠がある。
- 逸脱の有無が明示されている。
- review gate が必要な delta では、レビュー観点の結果が明示されている。
- 500 / 800 / 1000 行の閾値判定が必要な場合は根拠つきで書かれている。
- REVIEW delta で問題が見つかった場合は follow-up delta seeds が書かれている。
- FAIL の場合、再applyに必要な最小指示だけを書く。
- 1件でも FAIL があれば Overall は必ず FAIL である。
