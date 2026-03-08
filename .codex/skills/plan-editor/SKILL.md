---
name: plan-editor
description: 「plan.mdを作成/直す」「実装計画を書く/更新」「開発計画（実装/テスト/文書化）を整理する」「planに追加して」「planをアーカイブにして」などの依頼で使用。機能実装・テスト・文書化の計画をロケール（ja/en）に合わせて plan.md に作成・更新する。
---

# Plan Editor

## 基本方針
- 出力言語は `AGENTS.md` とロケールに合わせる（ja は日本語、en は英語）。
- 出力は plan.md 本文のみとし、前後の説明文を付けない。
- current / future / archive の3区分で管理する。
- 各章の切れ目に空行を1行入れる。

## 役割境界（Deltaとの分離）
- 本スキルの責務は `plan.md` の実行計画管理に限定する。
- ユーザー要件の差分定義・適用・検証・確定は `delta-request` / `delta-apply` / `delta-verify` / `delta-archive` の責務とする。
- `plan.md` の `archive` は計画タスクの完了記録であり、`delta-archive`（差分確定）とは別物として扱う。
- Active Delta がある間は、current の対象を In Scope に合わせ、Out of Scope の実装タスクを追加しない。
- Delta ID が未提示の要件実装タスクは、先に `delta-request` の作成を促す。

## 実装アイテムとDeltaの対応ルール
- current の実装アイテム1件は `delta-request` 1件の seed として扱う（原則 1:1）。
- 実装アイテムが大きい場合は複数 delta に分割し、親アイテムにぶら下げる（1:N は許可）。
- 実装アイテムには対応 Delta ID を明記する（未発行時は seed ラベルを付ける）。
- 実装アイテムの完了条件は「対応 Delta ID の `delta-archive` が PASS」で定義する。

## 生成フロー（厳守）
- 全体と機能が分かれているか確認する。
  - 分かれている場合: 全体は future に置き、着手中の機能を current に置く。
  - 全体のみの場合: 着手する部分を current に置く。
- 不足情報は提案案を示し、ユーザーの同意/修正を確認してから生成する。

## current のルール
- チェックリスト形式で高い粒度で記載する（`- [ ]` / `- [x]`）。
- 実装アイテムには Delta ID（または seed）を付ける。
- 「機能を実装 → 直後にテスト」を1セットにする。
- concept/spec/architecture の現状確認を最初に入れる。
- 文書化が必要なら最初に実施する（仕様書/設計書/運用文書の更新）。
- 実施中にうまく行かない場合は、デバッグメッセージ追加を含むデバッグ項目に組み替える。
- 機能部品から単体テストし、最終的にE2Eテストを行う。
- 最後に文書との整合性をテストする。
- 各項目は対象を具体化する（対象ファイル/機能/範囲を明記）。

## future のルール
- 大雑把な将来計画を記載する（concept未実現機能など）。
- チェックのないリスト形式で記載する。

## archive のルール
- 実施済みアイテムの記録。
- 「planをアーカイブにして」と言われたら current の完了項目を移動する。

## plan.md テンプレート（固定）
```markdown
# plan.md（必ず書く：最新版）

# current
- [ ] 例: [DOC] concept/spec/architecture の現状を確認する
- [ ] 例: [SEED-login] ログイン仕様変更の delta request を作成する
- [ ] 例: [DR-20260301-login] delta apply を実施する
- [ ] 例: [DR-20260301-login] delta verify を実施する
- [ ] 例: [DR-20260301-login] delta archive(PASS) を確認し正本へ同期する
- [ ] 例: [SEED-search] 検索機能改善の delta request を作成する
- [ ] 例: [DR-20260301-search] delta apply/verify/archive を完了する
- [ ] 例: 文書との整合性を確認する

# future
- 例: xxxx 機能
- 例: XXXをmmmしたい

# archive
- [x] 例: ccc
- [x] 例: dddd
```

## 整合性チェック
- current はチェックリスト形式になっているか確認する。
- 実装アイテムごとに Delta ID（または seed）が付いているか確認する。
- 実装アイテムの完了条件が `delta-archive PASS` になっているか確認する。
- 「実装→直後にテスト」の並びになっているか確認する。
- 単体→E2E→文書整合の順序が含まれているか確認する。
- future はチェックなしのリストになっているか確認する。
- archive は完了項目（`[x]`）のみか確認する。
