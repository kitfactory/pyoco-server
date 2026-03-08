# spec template and checks

## scale decision
| condition | output |
|---|---|
| UC <= 5 and Feature <= 8 and main roles <= 3 | single `spec.md` |
| otherwise | `spec.md` + feature-level specs |

If user explicitly requests output shape, prioritize user request.

## output format
- single spec: output `spec.md`
- split spec: output `spec.md` + `spec/feature-<id>.md` (or `xxxx_spec.md`)

## template (single spec)
```markdown
# <project name>

要件とは（レビュー者視点）＋ Given/When/Done ＋ MSG/ERR のID管理
※I/F詳細・API使用は書かない

# 要件一覧（Requirements）
| ID | 要件（固定書式・正常系のみ） | 関連UC-ID |
|---|---|---|
| REQ-0001 | XXXをしたら、YYYYする。 | UC-1 |

### [<prefix>-0001] XXXをしたら、YYYYする。
Given：前提状態
When：トリガ（ユーザー操作や内部イベント）
Done：完了条件（観測可能な結果）

#### エラー分岐（REQ-0001の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-<prefix>-0001 |  |  | MSG-<prefix>-0001 |

## メッセージID管理（MSG-xxxx）
| ID | 文面テンプレ | 出力先 | 発生条件 | 関連REQ/ERR |
|---|---|---|---|---|
| MSG-<prefix>-0001 |  |  |  | REQ-0001 |

## エラーID管理（ERR-xxxx）
| ID | 原因 | 検出条件 | ユーザーアクション | 再試行可否 | 関連MSG-ID | 関連REQ |
|---|---|---|---|---|---|---|
| ERR-<prefix>-0001 |  |  |  | 可/不可 | MSG-<prefix>-0001 | REQ-0001 |
```

## id rules
- REQ: `REQ-0001` 形式（4桁ゼロ埋め連番）
- detail heading: `[<prefix>-0001]`
- MSG/ERR: `MSG-<prefix>-0001` / `ERR-<prefix>-0001`
- 採番はプロジェクト単位で重複させない

## consistency checks
- concept の UC/Feature と spec の関連UC-IDが一致する。
- 全 REQ に Given/When/Done がある。
- 全 REQ のエラー分岐が ERR/MSG と紐づく。
- 正常系要件と異常系ID管理が分離されている。
