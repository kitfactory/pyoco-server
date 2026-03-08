---
name: concept-editor
description: 「concept.mdを作成」「conceptを作る/直す/修正」「concept文書を評価/レビュー」など、concept.mdの作成・更新・評価を行う。プロダクト概念・ユースケース・機能ブロック・主要データの整合性を担保しながら編集する固定11セクション形式。ロケール（ja/en）に合わせて出力する。
---

# Concept Editor

## 基本方針
- 出力言語は `AGENTS.md` とロケールに合わせる（ja は日本語、en は英語）。
- 出力は concept.md 本文のみとし、前後説明やレビュー文を同一出力に混ぜない。
- 本ファイルは優先ルールのみ保持し、詳細テンプレートは `references/` を参照する。

## 役割境界（Deltaとの分離）
- 本スキルの責務は `concept.md` の正本整備（全体整理/更新）に限定する。
- ユーザー要件の差分定義・適用・検証・確定は `delta-request` / `delta-apply` / `delta-verify` / `delta-archive` の責務とする。
- Delta ID が提示された場合、本スキルは「archive済み差分の正本同期」に限定して更新する。
- Active Delta がある間は In Scope に関係する章のみ更新し、Out of Scope の章は編集しない。
- Delta ID が未提示なら差分同期を実施しない。まず `delta-request` を作成する。
- `delta-archive` が PASS になる前に、実装確定を前提とした正本更新をしない。

## 実行モード
1. Canonical Mode（Delta ID なし）: concept 全体の整備を行う。
2. Delta Sync Mode（Delta ID あり）: `docs/delta/<Delta ID>.md` を読んで In Scope のみ同期する。

## 生成フロー（厳守）
1. 不足情報を確認する（重要度順、最大5件）。
2. 必須4観点（権限/保存方針/公開範囲/例外）を提案し、同意を得る。
3. `references/concept-template.md` に従って本文を作成する。
4. レビュー依頼がある場合のみ、本文出力の次メッセージでレビューする。

## 参照ファイル
- 詳細テンプレート/章ルール/整合チェック: `references/concept-template.md`
- 粒度合わせのサンプル: `references/sample-concept.md`

## 品質ゲート
- 11セクションが存在し、主要ID（F/UC/G）が整合している。
- Pain -> UC -> Features -> Layering -> Data の往復整合が成立する。
- Delta Sync Mode では更新章が In Scope に限定され、Out of Scope が不変である。
