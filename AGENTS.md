# AGENTS (共通テンプレート / Lean)

この AGENTS.md は **運用の最小ルール**を記載します。
詳細（レビューゲートのチェックリスト、Phase Close、spec/plan 分割ルール、DoD、エラー一覧など）は **`docs/OVERVIEW.md`** を正とします。
ただし、**ユーザー要件の実行手順は delta フロー（request → apply → verify → archive）を最優先**とします。
機密情報は記載しないでください。

## Top 5（必ず守る）
1. **ユーザー要件は必ず delta 4ステップで処理**：`delta request → delta apply → delta verify → delta archive`。
2. **矛盾時は delta を優先**：AGENTS.md / OVERVIEW / 既存メモと矛盾したら、当該 Delta ID の定義（In Scope / Out of Scope / AC）を優先する。
3. **入口は `docs/OVERVIEW.md`**（全体像・現在地・リンク集）。作業前後で必ず確認/更新する。
4. **`docs/plan.md` は current / review timing / future / archive summary / archive index で管理**し、詳細 archive は monthly file へ分離する。
5. **レビューゲートで必ず停止**：自己レビュー → 完成と判断できたらユーザー確認 → 合意で次へ。

## 要件対応プロトコル（Delta-First / 必須）
### Step 1: `delta request`（定義）
- ユーザー要件から **最小差分** を定義する（In Scope / Out of Scope / 受入条件）。
- この時点で「今回やらないこと」を明文化し、巻き込みを防ぐ。

### Step 2: `delta apply`（適用）
- request で定義した差分だけを実装する。
- request にない“ついで修正”は実施しない。

### Step 3: `delta verify`（検証）
- 受入条件を満たすかを検証する。
- Out of Scope への変更があれば FAIL とし、後工程へ流さない。
- plan↔delta↔archive の整合確認と長大コードの確認は `project-validator` skill を使う。

### Step 4: `delta archive`（確定）
- verify が PASS の差分だけを履歴化してクローズする。
- 大機能完了時は `Delta Type: REVIEW` を先に通し、`docs/delta/REVIEW_CHECKLIST.md` で点検する。
- ユーザーは `review deltaを回して` と手動発動してよい。
- archive で新規要件を追加しない。

### 逸脱防止ルール
- すべての変更は AC に紐づける。紐づかない変更は削除または次の delta に分離する。
- スコープ変更が必要になったら、現在の delta を止めて request を更新してから再開する。

## 役割境界（Canonical Docs と Delta）
- `concept/spec/architecture` 系スキルは **全体文書の正本整備**を担当する。
- ユーザー要件への対応は **delta 4ステップ**（request/apply/verify/archive）で実行する。
- `spec-editor` / `architecture-editor` / `concept-editor` は delta を作成・実行しない。
- Delta ID が無い要件実装は開始せず、先に `delta request` を作成する。
- `docs/plan.md` の実装アイテム1件は `delta request` 1件の seed として扱う（原則 1:1）。
- 実装アイテムが大きい場合は複数 delta へ分割してよい（1:N）。
- delta の記録は `docs/delta/*.md`（Markdown）を正本とし、JSON/YAML の副管理を要求しない。
- `delta-archive` が PASS のときのみ、正本へ最小差分で同期する。
- Active Delta がある間、正本更新は In Scope に限定し、Out of Scope は変更しない。
- `docs/plan.md` の archive は計画タスクの完了記録であり、`delta archive`（差分確定）とは別物として扱う。

## 設計指示（必須 / 短縮版）
- **ユーザー向けI/Fは単純に**：引数・型の種類を最小化し、内部都合の型/状態を漏らさない。
- **データモデルは共通属性で集約**：似た概念のオブジェクトを乱立させず、共通属性を抽出してコアに寄せる。
- **拡張は合成で**：差分は `details/meta` 等の入れ子で表現してI/Fを安定化（ただしゴッドデータ禁止）。
- **`details/meta` のゴミ箱化禁止**：キー集合/構造は spec で定義し、「不明キー何でもOK」を許さない。肥大化したらコアへ昇格。
- **ゴッドAPI/ゴッドクラス禁止**：最小I/F・最小データで責務分割する。
- **依存方向の逆流禁止**：レイヤー責務と依存方向は architecture に明記し、それに従う（外→内固定）。
- **設計変更提案の出力順を固定**：変更分類→価値フロー→最小案→レイヤー配置→境界契約→状態遷移→エラー設計→観測性→テスト→境界チェック→変更前チェック→実装タスク分解。
- **設計指示の衝突優先**：`spec.md > architecture.md > OVERVIEW/AGENTS > 設計補助ガイド`。

## 作業開始 60 秒ルーチン（初動固定）
1) `docs/OVERVIEW.md`：現在フェーズ / 今回スコープ / 参照リンクを確認
2) `docs/concept.md`：対象 Spec ID と範囲を確認
3) `docs/spec.md`：該当章へ移動（必要なら分割する）
4) `docs/plan.md`：current チェックリストと詳細リンクを確認
5) （任意）フェーズ運用時のみ `docs/phases/<PHASE>/` を確認

## 更新の安全ルール（強すぎない版）
### そのまま適用してよい変更（合意不要）
- 誤字修正、リンク更新、追記（既存の意味を変えない）
- plan のチェック更新（チェックボックスの進捗）
- 既存方針に沿った小さな明確化（文章の補足）

### “提案→合意→適用” が必要な変更（事故防止）
- 大量削除、章構成の変更、ファイルの移動/リネーム
- Spec ID / Error ID の変更、互換性に影響する仕様変更
- API / データモデルの形を変える設計変更
- セキュリティ対応・重大バグ修正で挙動が変わるもの（提案は簡潔でよいが必須）

## 言語・コメント
- AGENTS.md が日本語の場合、`docs/**` は日本語で作成する
- ソースコードのコメントは **日本語 + 英語を併記**

## 言語別指針 (Python)
- Python: `uv` + `.venv` 仮想環境、`pytest`、Lint/Format（`ruff`/`black` など）を推奨。
- 環境変数/`.env` の必要キーと利用箇所を明示し、`.env.sample` は生成しないでください。

## 対応エージェント
- ターゲット: Codex
- 他のエージェント指定時は CLI オプション `--agent` を使用
- skills の配置先は `--skills none|workspace|user` で切り替える

## サンプル（最低限）
- 成功例: `bon --dir ./project --lang ts --agent codex --skills workspace`
- 失敗例: `bon --agent unknown` → `[bon][E_AGENT_UNSUPPORTED] Unsupported agent: unknown`

## 詳細は OVERVIEW を正とする
`docs/OVERVIEW.md` を参照する。