---
name: delta-archive
description: 「delta archive」「差分を確定したい」「履歴化して閉じたい」などの依頼で使用。verifyで合格した差分を履歴化し、仕掛かりを残さず変更サイクルを完了させる。
---

# Delta Archive

## 目的
- PASS 済みの差分を確定し、履歴として残す。
- 次の変更へ進めるために状態を閉じる。

## 前提
- delta-verify が Overall PASS であること。

## 厳守ルール（逸脱禁止）
- archive フェーズで追加実装しない。
- FAIL 状態の差分は archive しない。
- 記録は事実のみ（推測・評価語を混ぜない）。
- archive 出力は `docs/delta/<Delta ID>.md` に追記または確定保存する。
- `review gate required: Yes` の delta は、レビュー結果が PASS でなければ archive しない。
- 未解決の設計崩れ、文書ズレ、データ肥大、長大コードを抱えたまま archive しない。
- `Delta Type = REVIEW` で問題が見つかった場合は、follow-up delta seeds を記録してから archive する。

## 実行フロー
1. Delta ID と対象差分を確定する。
2. request/apply/verify の要点を記録する。
3. review gate の通過有無を確認する。
4. 未解決事項の有無を明示する。
5. クローズ状態を宣言する。

## 出力テンプレート（固定）
```markdown
# delta-archive

## Delta ID
- （requestと同一）

## クローズ判定
- verify結果: PASS
- review gate: PASSED / NOT REQUIRED
- archive可否: 可

## 確定内容
- 目的:
- 変更対象:
- 非対象:

## 実装記録
- 変更ファイル:
- AC達成状況:

## 検証記録
- verify要約:
- 主要な根拠:

## 未解決事項
- なし / あり（内容を列挙）

## 次のdeltaへの引き継ぎ（任意）
- Seed-01:
```

## 品質ゲート（出力前チェック）
- verify が PASS である。
- review gate が必要な場合は PASS である。
- 変更対象・非対象が記録されている。
- 未解決事項の有無が明示されている。
- REVIEW delta で問題が見つかった場合は次の delta seeds が記録されている。
- archive で新規要件を追加していない。
- 保存先（`docs/delta/<Delta ID>.md`）が明記されている。
