# architecture template and checks

## required sections
```markdown
# architecture.md（必ず書く：最新版）
#1.アーキテクチャ概要（構成要素と責務）
#2.concept のレイヤー構造との対応表
#3.インターフェース設計（UI/APP境界, 外部I/F, 内部I/F, 依存先I/F, 型定義）
#4.主要フロー設計（成功/失敗）
#5.データ設計（永続化・整合性・マイグレーション）
#6.設定：場所／キー／既定値
#7.依存と拡張点（Extensibility）
#7.5.依存関係（DI）
#8.エラーハンドリング設計
#9.セキュリティ設計
#10.観測性
#11.テスト設計
#12.配布・実行形態
#13.CLI：コマンド体系／引数／出力／exit code
```

## interface requirements
- UI/APP境界I/Fは UC 単位で書く。
- 内部I/Fはクラス/メソッド単位で書く。
- 引数は型・意味・値範囲/制約・必須性を明記する。
- 戻り値は型と主要フィールドを明記する。
- 例外は発生場所/原因を追跡可能に書く。
- List/Array は要素型を必ず明記する。

## consistency checks
- concept のレイヤー/UC/データと整合する。
- spec の ERR/MSG 命名と一致する。
- 依存方向が逆流しない。
- エラーハンドリング方針と主要フローの失敗条件が矛盾しない。
