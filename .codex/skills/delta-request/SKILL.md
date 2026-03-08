---
name: delta-request
description: 「delta request」「差分要求を作る」「変更を最小スコープで定義したい」などの依頼で使用。変更要求を差分に閉じて定義し、apply/verify に渡せる要求仕様を作る。
---

# Delta Request

## 目的
- 変更要求を「最小差分」に閉じて定義する。
- apply/verify が迷わない入力を作る。
- 1つのユーザー要求を 1つの Delta ID に固定する。

## 厳守ルール（逸脱禁止）
- 要求は「今回変えること」に限定し、背景説明を膨らませない。
- 非対象（今回変えないこと）を必ず明記する。
- 設計刷新・広範囲リファクタ・将来要望を混ぜない。
- 不明点は推測で埋めず、未確定として残す。
- 同時に複数 Delta を進めない（常に Active Delta は 1 件）。
- 差分定義は `docs/delta/<Delta ID>.md` として保存する。
- Delta Type を必ず 1 つ選ぶ（FEATURE / REPAIR / DESIGN / REVIEW / DOCS-SYNC / OPS）。
- 大機能、設計影響、レイヤー横断、文書同期影響がある場合は `review gate required: Yes` とする。
- `Delta Type = REVIEW` は点検専用とし、広範囲修正を混ぜない。
- ユーザーが `review deltaを回して` と言った場合は `Delta Type = REVIEW` を選ぶ。
- 同一 plan item が 3 delta 以上になった場合、または REVIEW 以外の delta が 5 件続いた場合は `Delta Type = REVIEW` を提案してよい。

## 作成フロー
1. ユーザー要求から「明示要求」を抽出する。
2. Delta Type を決める。
3. 最小スコープを決める（対象ファイル/機能/振る舞い）。
4. 非対象を列挙する（巻き込み防止）。
5. 受入条件を Given/When/Then または観測可能な条件で定義する。
6. `review gate required` の要否を決める。
7. `Delta Type = REVIEW` の場合は `docs/delta/REVIEW_CHECKLIST.md` を Review Focus に入れる。
8. apply へ渡す作業境界を確定する。

## 出力テンプレート（固定）
```markdown
# delta-request

## Delta ID
- DR-YYYYMMDD-<short-name>

## Delta Type
- FEATURE / REPAIR / DESIGN / REVIEW / DOCS-SYNC / OPS

## 目的
- （1-2行）

## 変更対象（In Scope）
- 対象1:
- 対象2:

## 非対象（Out of Scope）
- 非対象1:
- 非対象2:

## 差分仕様
- DS-01:
  - Given:
  - When:
  - Then:
- DS-02:
  - Given:
  - When:
  - Then:

## 受入条件（Acceptance Criteria）
- AC-01:
- AC-02:

## 制約
- 制約1:
- 制約2:

## Review Gate
- required: Yes/No
- reason:

## Review Focus（REVIEW または review gate required の場合）
- checklist: `docs/delta/REVIEW_CHECKLIST.md`
- target area:

## 未確定事項
- Q-01:
```

## 品質ゲート（出力前チェック）
- Delta Type が 1 つに決まっている。
- In Scope が最小単位になっている。
- Out of Scope が具体的に書かれている。
- AC が観測可能で、曖昧語（「いい感じ」「適切に」など）を含まない。
- review gate の要否が明示されている。
- REVIEW delta では Review Focus が明示されている。
- 未確定事項と確定事項が混在していない。
- 変更対象ファイル候補が In Scope と矛盾していない。
