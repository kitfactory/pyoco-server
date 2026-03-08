# design assist guide (change-oriented)

Use this guide when the user asks for design work tied to a concrete change request.

## precedence
If instructions conflict, apply this order:
1. `spec.md`
2. `architecture.md`
3. `docs/OVERVIEW.md` / `AGENTS.md`
4. this guide

## design constraints
- Avoid over-design and mixed responsibilities.
- Fix dependency direction to outer -> inner.
- Keep interfaces minimal and domain invariants explicit.

## input slots
- 変更要求
- 既存の仕様/制約（あれば）
- 既存コード構造（簡易）
- 外部依存（DB/API/IPC/LLMなど）
- 期待するユーザー価値（価値フロー）

## required output order
1. 変更分類: `[仕様追加/設計変更/実装修正]`
2. 価値フロー: ユーザー価値（1〜3行）
3. 最小案: 増やす責務・データ・状態を最小単位で列挙
4. レイヤー配置:
   - Domain: 型・不変条件
   - UseCase: 手順・状態遷移・入出力
   - Adapter: 変換のみ（UI/外部I/O）
   - Infrastructure: 技術詳細のみ（DB/API/LLM）
5. 境界と契約:
   - Port/Interface（必要最小）
   - 入力前提 / 出力結果（成功/失敗）
   - 例外 -> 仕様化エラーへの正規化
6. 状態遷移・整合性:
   - 状態一覧
   - 許可遷移表
   - 競合方針（単一ライタ/楽観ロック/排他）
   - 冪等性（識別子/重複防止）
7. エラー設計（最低4種）:
   - 入力不備 / 整合性違反 / タイムアウト / 依存障害
   - 各エラーに「検知点・原因・利用者文言・再試行可否」
8. 観測性:
   - 主要イベントと who/what/target/when/result
   - 重要判定の根拠追跡（入力・制約・判定結果）
9. テスト最小基準:
   - Domain 単体（不変条件/遷移）
   - UseCase（正常1 + 主要失敗1以上）
   - Adapter/Infra（契約 or 結合）
10. 境界チェック（Yes/No）:
   - UseCaseにSQL/HTTP/IPCが漏れていないか 等 7項目
11. 変更前チェック10項目（Yes/No）:
   - No がある場合は分解案を提示して終了
12. 実装タスク分解:
   - ファイル/クラス単位のタスク

