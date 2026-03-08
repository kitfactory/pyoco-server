# Spawn / YAML Bundle 要件定義書

## 1. 文書の位置づけ
- 本文書は、`pyoco-server` に追加を検討している「workflow から workflow を起動する orchestration 機能」の要件定義をまとめたものとする。
- 既存の `docs/spec.md` は現行実装の契約を表す正本であり、本機能の実装契約はまだ含めない。
- 本文書は、後続の `concept` / `spec` / `architecture` / `plan` へ展開する前段の要求整理を目的とする。

## 2. 背景
- `pyoco-server` は、YAML で定義した workflow を HTTP Gateway 経由で投入し、worker が分散実行する軽量バックエンドである。
- 現状の YAML 実行は「1 run が 1 workflow を実行する」前提であり、実行中 run が別 workflow の run を生成する機能は持たない。
- 一方で、研究・開発用途では、親 workflow が試行条件を生成し、子 workflow を複数回実行し、その結果を集約したい要求がある。
- 代表例は、Study が Trial を起動するパラメータ探索である。ただし本要求は最適化に限定せず、前処理・学習・推論・評価・集約の親子 workflow にも適用できる基盤機能として扱う。

## 3. 目的
- `pyoco-server` が 1 枚の YAML bundle を受理し、bundle 内に定義された複数 workflow を扱えるようにする。
- `submit.entry_workflow` を root run として起動できるようにする。
- workflow 内の `spawn` task により、同一 bundle 内の別 workflow を child run として起動できるようにする。
- `spawn` を含む entry workflow を承認対象として扱えるようにする。
- root run / child run / bundle hash / spawn 元 task を追跡し、監査と再現性を確保する。

## 4. 非目標
- child run からさらに孫 workflow を spawn すること。
- 外部 registry 名、外部 YAML、外部 URL、実行中の別 bundle を参照して workflow を解決すること。
- YAML 上で child run の timeout / retry / queue / policy を細かく指定すること。
- `approval: true` のような明示フラグを YAML に持たせること。
- 厳格マルチテナント向けの多段権限委譲や、複雑な delegation policy を同時に導入すること。

## 5. 基本原則

### 5.1 1 枚 YAML Bundle
- submit 単位は単一の YAML bundle とする。
- 親 workflow、子 workflow、submit 情報は同一 YAML に同居させる。
- 実行時に bundle 外の workflow 定義を取り込まない。

### 5.2 `spawn` を基盤概念とする
- `pyoco-server` 側の基盤語彙は `spawn` とする。
- `trial` は最適化ドメインで使う語彙であり、基盤仕様の予約語にしない。

### 5.3 承認判定は静的解析で行う
- YAML に承認フラグは持たせない。
- サーバーが bundle を静的解析し、`submit.entry_workflow` から到達可能な `spawn` task が存在する場合に「承認必須」と判定する。

### 5.4 再帰禁止
- child run は `spawn` を実行できない。
- 実効深さは root run と child run の 2 層までに固定する。

### 5.5 サーバー側ポリシー固定
- child run 数、並列数、使用 tag、timeout、retry、polling、結果参照範囲などの安全制御は YAML ではなくサーバー設定で固定する。

## 6. 用語
- bundle: 複数 workflow と submit 情報を含む 1 枚の YAML 文書。
- entry workflow: `submit.entry_workflow` で指定される root run の起点 workflow。
- root run: bundle 提出時に最初に生成される run。
- child run: `spawn` task により root run から生成される run。
- spawn task: `spawn: <workflow_name>` を持ち、同一 bundle 内 workflow の child run を起動する task。
- bundle hash: 受理した bundle 全体 bytes から計算する不変ハッシュ。
- approval required bundle: entry workflow から到達可能な `spawn` task を含み、submit 後に承認待ち遷移が必要な bundle。

## 7. 機能要件

### FR-1. YAML bundle を受理できること
- `pyoco-server` は、複数 workflow 定義と submit 情報を持つ 1 枚の YAML bundle を受理できること。
- bundle は schema version を持ち、サーバーは version ごとに検証できること。

### FR-2. entry workflow を root run として起動できること
- `submit.entry_workflow` で指定された workflow 名を解決し、root run を生成できること。
- `submit.inputs` は entry workflow の入力値として root run に渡せること。

### FR-3. `spawn` task で child run を起動できること
- workflow 内 task が `spawn` を持つ場合、サーバーは同一 bundle 内の workflow 名を解決して child run を生成できること。
- child run は独立した run として run_id を持ち、worker によって通常 run と同様に実行されること。

### FR-4. 親 workflow が child run 完了を待機できること
- 親 workflow は child run の完了を待機できること。
- wait 中に child run の最終状態を判定できること。

### FR-5. 親 workflow が child run 結果要約を取得できること
- 親 workflow は child run の終了後に、少なくとも `status`、`outputs`、`summary metrics`、`artifacts`、`error summary` の要約を取得できること。
- 取得範囲はサーバー側ポリシーで制御できること。

### FR-6. 承認フローを持てること
- entry workflow から到達可能な `spawn` task が存在する場合、submit 後の root run は承認待ち状態へ遷移できること。
- 承認後に queue へ投入できること。
- 不承認または取消時に terminal 相当の扱いへ収束できること。

### FR-7. 親子関係を保存できること
- root run / child run について少なくとも以下を保存できること。
  - `run_id`
  - `root_run_id`
  - `parent_run_id`
  - `workflow_name`
  - `bundle_hash`
  - `spawned_from_task`

### FR-8. bundle hash を run に継承できること
- 受理した bundle 全体のハッシュを算出し、root run と child run の双方に記録できること。
- 後から「どの bundle 由来の run か」を追跡できること。

### FR-9. 監査情報を取得できること
- 少なくとも以下を監査できること。
  - bundle hash
  - entry workflow 名
  - 承認有無
  - root run / child run 関係
  - spawn 実行回数
  - child run 一覧
  - submit 時刻 / 実行時刻 / 完了時刻

## 8. 状態要件
- orchestration bundle の root run は少なくとも以下の状態を取り得ること。
  - `PENDING_APPROVAL`
  - `PENDING`
  - `RUNNING`
  - `COMPLETED`
  - `FAILED`
  - `CANCELLED`
- child run は承認対象にしない前提とし、通常 run と同等の queued/running/terminal 遷移で扱うこと。
- child run は `spawn` を持っていても実行時に拒否されること。

## 9. セキュリティ要件

### SR-1. spawn 先は同一 bundle 内のみ
- `spawn` の参照先は同一 bundle の `workflows` に存在する workflow 名のみとする。
- 以下は禁止する。
  - 外部 YAML 読み込み
  - 外部 URL 参照
  - 外部 workflow registry 名参照
  - 実行中の別 bundle 取得

### SR-2. child の再 spawn を禁止する
- child run 実行中に `spawn` task が評価された場合は拒否すること。
- 拒否時は監査可能なエラーとして記録すること。

### SR-3. 制約はサーバー設定で固定する
- 以下は YAML ではなくサーバー設定で管理すること。
  - 最大 child run 数
  - 最大並列 child run 数
  - child run に使用可能な queue / tag
  - timeout
  - retry policy
  - polling interval
  - result access policy
  - 承認判定ルール

### SR-4. bundle 不変性を担保する
- 実行中に bundle 外の定義へ解決先が変化しないこと。
- root run と child run は同一 bundle hash を継承すること。

## 10. YAML bundle 仕様

### 10.1 トップレベル構造
```yaml
version: 1

workflows:
  ...

submit:
  entry_workflow: ...
  inputs:
    ...
```

### 10.2 `workflows`
- `workflows` は bundle 内の workflow 定義を名前付きで保持する map とする。
- workflow 名は bundle 内で一意であること。
- `submit.entry_workflow` および `spawn` はこの workflow 名を参照すること。

例:
```yaml
workflows:
  study:
    tasks:
      ...
    flow:
      graph: |
        ...

  trial:
    tasks:
      ...
    flow:
      graph: |
        ...
```

### 10.3 task 種別
- task は通常 task と spawn task を持てること。

通常 task:
```yaml
tasks:
  train_model:
    callable: pyoco_inspect.tasks:train_model
```

spawn task:
```yaml
tasks:
  run_trial:
    spawn: trial
```

spawn task の制約:
- `spawn` 先は `workflows` 内 workflow 名のみとする。
- child 側 workflow 自身は `spawn` を使ってはならない。
- child run にはサーバー側固定ポリシーを適用する。

### 10.4 `flow.graph`
- `flow.graph` では通常 task と spawn task を同等にグラフへ配置できること。
- サーバーは spawn task の実行時に child run を生成し、親 workflow に結果を返せること。

### 10.5 `submit`
```yaml
submit:
  entry_workflow: study
  inputs:
    max_trials: 30
    objective_metric: macro_f1
```

- `entry_workflow` は root run の起点 workflow 名を指定すること。
- `inputs` は entry workflow に渡す自由構造の YAML 値を持てること。

## 11. 承認判定ルール
- YAML に approval フラグは持たせない。
- サーバーは submit 時に bundle を静的解析し、entry workflow から到達可能な `spawn` task がある場合に承認必須と判定する。
- 判定結果は少なくとも次の 2 区分を持つこと。
  - `spawn` なし: 通常 workflow bundle
  - `spawn` あり: orchestration bundle（承認対象）

## 12. 最小例
```yaml
version: 1

workflows:
  study:
    tasks:
      start_study:
        callable: pyoco_experiment.tasks:start_study
      suggest_params:
        callable: pyoco_experiment.tasks:suggest_params
      run_trial:
        spawn: trial
      update_study:
        callable: pyoco_experiment.tasks:update_study
      finalize_study:
        callable: pyoco_experiment.tasks:finalize_study
    flow:
      graph: |
        start_study
        >> repeat(
             suggest_params
             >> run_trial
             >> update_study
           )
        >> finalize_study

  trial:
    tasks:
      load_dataset:
        callable: pyoco_inspect.tasks:load_dataset
      preprocess:
        callable: pyoco_inspect.tasks:preprocess
      train_model:
        callable: pyoco_inspect.tasks:train_model
      evaluate_model:
        callable: pyoco_inspect.tasks:evaluate_model
      complete_run:
        callable: pyoco_experiment.tasks:complete_run
    flow:
      graph: |
        load_dataset
        >> preprocess
        >> train_model
        >> evaluate_model
        >> complete_run

submit:
  entry_workflow: study
  inputs:
    experiment_name: bottle-cap-optimization
    study_name: resnet18-search
    max_trials: 30
    objective_metric: macro_f1
```

## 13. サーバー側固定設定項目
- spawn を含む workflow の承認要否
- child run の spawn 禁止
- 最大 child run 数
- 最大並列 child run 数
- 使用可能 queue / tags
- timeout
- retry policy
- polling interval
- child result 取得範囲
- 親子 run relation 保存方式
- bundle hash 記録方式

## 14. 受け入れ条件
- 単一 bundle から root run を起動できること。
- bundle 内 workflow 名だけで child run を起動できること。
- child run が再 spawn しようとした場合に拒否されること。
- bundle hash が root run / child run の双方に記録されること。
- 承認対象 bundle が submit 時に承認待ちへ遷移できること。
- 親 run から child run の完了待機と結果要約参照ができること。
- 後から root run / child run 関係と spawn 元 task を追跡できること。

## 15. 設計に持ち越す論点
- bundle 提出用 API を既存 `POST /runs/yaml` に拡張するか、別 endpoint に分離するか。
- 承認操作を HTTP API / CLI / Dashboard のどこまで提供するか。
- bundle 本文をどこまで保存し、どこからは hash と manifest のみを保存するか。
- child result の「summary metrics」「artifacts」の標準表現をどこまで固定するか。
- 親 run の child wait 実装を worker 内部 polling にするか、別 coordinator 機能を持つか。
