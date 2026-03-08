---
name: spec-editor
description: 「仕様書を作る/直す」「spec.mdを作成/修正」「仕様書(spec.md相当)を作って/直して」などの依頼で使用。concept.mdを参照して規模を判断し、全体または機能単位の仕様書をロケール（ja/en）に合わせて整合性を保って作成・更新する。
---

# Spec Editor

## 基本方針
- 出力言語は `AGENTS.md` とロケールに合わせる（ja は日本語、en は英語）。
- 出力は仕様書本文のみとし、前後説明やレビュー文を同一出力に混ぜない。
- 本ファイルは優先ルールのみ保持し、詳細テンプレートは `references/` を参照する。
- I/F詳細・API使用の詳細は書かず、要件レベルを維持する。

## 役割境界（Deltaとの分離）
- 本スキルの責務は `spec.md`（および機能別仕様）の正本整備に限定する。
- ユーザー要件の差分定義・適用・検証・確定は `delta-request` / `delta-apply` / `delta-verify` / `delta-archive` の責務とする。
- Delta ID が提示された場合、本スキルは「archive済み差分の正本同期」に限定して更新する。
- Active Delta がある間は In Scope に関連する要件/章のみ更新し、Out of Scope の要件/章は編集しない。
- Delta ID が未提示なら差分同期を実施しない。まず `delta-request` を作成する。
- `delta-archive` が PASS になる前に、確定要件として書き換えない（未確定は未確定として記載する）。

## 実行モード
1. Canonical Mode（Delta ID なし）: concept から全体仕様/機能別仕様を整備する。
2. Delta Sync Mode（Delta ID あり）: `docs/delta/<Delta ID>.md` を読んで In Scope のみ同期する。

## 生成フロー（厳守）
1. concept.md の有無を確認し、必要なら要約を依頼する。
2. `references/spec-template.md` の規模判定で出力単位（全体/機能別）を決める。
3. 不足情報を提案し、同意後に本文を生成する。
4. レビュー依頼がある場合のみ、本文出力の次メッセージでレビューする。

## 参照ファイル
- 詳細テンプレート/IDルール/整合チェック: `references/spec-template.md`

## 品質ゲート
- REQ/Given-When-Done/ERR/MSG の対応が崩れていない。
- concept の UC/Feature が仕様で網羅されている。
- Delta Sync Mode では更新章が In Scope に限定され、Out of Scope が不変である。
