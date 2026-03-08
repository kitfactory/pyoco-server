# concept template and checks

## output template
```markdown
# concept.md（必ず書く：最新版）
#1.概要（Overview）（先頭固定）
- 作るもの（What）：
- 解決すること（Why）：
- できること（主要機能の要約）：
- 使いどころ（When/Where）：
- 成果物（Outputs）：
- 前提（Assumptions）：

#2.ユーザーの困りごと（Pain）

#3.ターゲットと前提環境（詳細）

#4.採用する技術スタック（採用理由つき）

#5.機能一覧（Features）
| ID | 機能 | 解決するPain | 対応UC |
|---|---|---|---|
| F-1 |  |  | UC-1 |

#6.ユースケース（Use Cases）
| ID | 主体 | 目的 | 前提 | 主要手順（最小操作） | 成功条件 | 例外/制約 |
|---|---|---|---|---|---|---|
| UC-1 |  |  |  |  |  |  |

#7.Goals（Goalのみ／ユースケース紐づけ必須）
- G-1: （対応：UC-1）

#8.基本レイヤー構造（Layering）
| レイヤー | 役割 | 主な処理/データ流れ |
|---|---|---|
| プレゼンテーション層 |  |  |

#9.主要データクラス（Key Data Classes / Entities）
| データクラス | 主要属性（不要属性なし） | 用途（対応UC/Feature） |
|---|---|---|
|  |  |  |

#10.機能部品の実装順序（Implementation Order）

#11.用語集（Glossary）
```

## section rules
- #1 は6項目すべて埋める。
- #4 は採用理由を1行以上書く。
- #5 は F-1, F-2... 採番。
- #6 は UC-1, UC-2... 採番。主要手順は最小操作で具体化。
- #7 は G-1, G-2... 採番し、各 Goal に「対応：UC-?」を付与。
- #10 は番号付きで実装順序を示す。
- テンプレート外の追加セクションは作らない。

## consistency checks
- Pain -> UC -> Features -> Layering -> Data の順で対応を確認する。
- Data -> Layering -> Features -> UC -> Pain の逆方向も成立させる。
- 各 Feature は Pain と UC に紐づける。
- 未使用データ（Feature/UC に出ない Data Class）を残さない。
- UC は最小操作で完結させる。
