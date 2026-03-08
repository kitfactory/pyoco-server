---
name: architecture-editor
description: 「architecture.mdを作成/直す」「設計書を書く/修正」「アーキテクチャ設計をまとめる」などの依頼で使用。concept.mdを参照してソフトウェア設計を行い、必要観点を網羅したarchitecture.mdをロケール（ja/en）に合わせて作成・更新する。
---

# Architecture Editor

## 基本方針
- 出力言語は `AGENTS.md` とロケールに合わせる（ja は日本語、en は英語）。
- 出力は設計書本文のみとし、前後説明やレビュー文を同一出力に混ぜない。
- 本ファイルは優先ルールのみ保持し、詳細テンプレートは `references/` を参照する。
- concept/spec と用語・ID・例外命名を整合させる。

## 役割境界（Deltaとの分離）
- 本スキルの責務は `architecture.md` の正本整備（全体設計の整理/更新）に限定する。
- ユーザー要件の差分定義・適用・検証・確定は `delta-request` / `delta-apply` / `delta-verify` / `delta-archive` の責務とする。
- Delta ID が提示された場合、本スキルは「archive済み差分の正本同期」に限定して更新する。
- Active Delta がある間は In Scope に関係する設計要素のみ更新し、Out of Scope の設計要素は編集しない。
- Delta ID が未提示なら差分同期を実施しない。まず `delta-request` を作成する。
- `delta-archive` が PASS になる前に、実装確定済みを前提とした設計記述へ更新しない。

## 実行モード
1. Canonical Mode（Delta ID なし）: architecture 全体整備を行う。
2. Delta Sync Mode（Delta ID あり）: `docs/delta/<Delta ID>.md` を読んで In Scope のみ同期する。

## 生成フロー（厳守）
1. concept.md の有無を確認する（未提示なら作成を推奨）。
2. spec.md の有無を確認し、ERR/MSG 命名を合わせる。
3. 設計変更要求がある場合は `references/design-assist-guide.md` の入力/出力順に従って設計案を作成する。
4. `references/architecture-template.md` に従って本文を生成する。
5. 依存方向は「外→内」（Adapter/Infrastructure -> UseCase -> Domain）に固定する。
6. 仕様衝突時の優先順位は `spec.md > architecture.md > OVERVIEW/AGENTS > design-assist-guide` を適用する。
7. 過剰設計（未要求の将来拡張・責務混在）を禁止し、最小責務で分割する。
8. レビュー依頼がある場合のみ、本文出力の次メッセージでレビューする。

## 参照ファイル
- 詳細テンプレート/境界契約/整合チェック: `references/architecture-template.md`
- 設計補助ガイド（入力項目/12段出力/境界チェック）: `references/design-assist-guide.md`

## 品質ゲート
- レイヤー責務・依存方向・I/F 契約・例外設計が整合する。
- spec の ERR/MSG 命名と矛盾しない。
- Delta Sync Mode では更新要素が In Scope に限定され、Out of Scope が不変である。
