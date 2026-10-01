# ローカル開発と実装の詳細

[English](LOCAL-DEVELOPMENT.md) · [READMEへ戻る](../README.ja.md)

以下のコマンドは、すべてリポジトリのルートで実行します。
コンテナだけで試す最短の例は、[READMEのクイックスタート](../README.ja.md#apiを1つ試す)を参照してください。
手動起動の例には、BuildKitと`up --wait`に対応したDocker Compose v2、起動済みのDocker daemon、
curlが必要です。`make`を使う例にはMakeも必要です。コンテナのビルドには、各言語のツールチェーンを
ホストへ入れる必要はありません。完全な受入テストにはPythonと各実装の固定ホストツールチェーンも
必要です。正確な前提条件は[Contributing](../CONTRIBUTING.md)を参照してください。

APIと受入テストはホストの`8080`ポートを共有するため、順番に実行してください。
使い捨てのbenchmark用Composeプロジェクトだけを指定します。
**`make down`は選択したプロジェクトのコンテナ、ネットワーク、孤立コンテナ、volumeを削除します。
`make db-reset`は同じ削除を行ってからPostgreSQLを再作成します。どちらもtmpfs上のDB状態を失います。**
`COMPOSE_PROJECT_NAME`や`COMPOSE`を変更した場合は、起動とcleanupで同じ指定を使ってください。
残す必要のあるデータやサービスのプロジェクトには実行しないでください。手動操作を中断した場合も、
対象プロジェクトを確認してcleanupしてください。

登録、CI対象、有効な比較グループ、公開済み測定結果は別です。
共通の状態説明は[登録・比較グループガイド](IMPLEMENTATIONS.md#registered-and-measured-implementations)にまとめています。
実行方式と検証の専用ガイド:

- [Rust / Axum](AXUM.md)
- [Node.js / Express](NODE-EXPRESS.md)
- [Python / Flask](FLASK.md)
- [Java / Spring Boot](JAVA-SPRING-BOOT.md)

以下にbaseline実装と共通のローカル操作を記載します。

## ローカルPostgreSQL環境

Docker Compose v2とMakeが必要です。共通DBには、ダイジェストで固定した公式の`postgres:18.6-bookworm`イメージを使用します。Composeプロジェクト内の`benchmark`ネットワーク上で`postgres`サービスとして動作し、ホスト側のポートは公開しません。

| 設定 | 値 |
|---|---|
| Service / host | `postgres` |
| 内部ポート | `5432` |
| Database | `benchmark` |
| User | `benchmark` |
| Password | `benchmark` |

これらは理解しやすさを優先したローカル専用の初期値であり、本番用の認証情報ではありません。APIサービスは、`docker-compose.yml`の共通設定`DATABASE_HOST`、`DATABASE_PORT`、`DATABASE_NAME`、`DATABASE_USER`、`DATABASE_PASSWORD`を使用します。

```bash
make db-up      # PostgreSQLを起動し、healthy状態とfixtureを確認する
make db-check   # 起動中DBのfixtureを確認する
make db-reset   # 現在のDB状態を破棄し、fixtureを再作成する
make test-db    # 起動・リセット・クリーンアップのacceptance checkを実行する
make down       # コンテナとプロジェクトネットワークを削除する
```

PostgreSQLのデータは`tmpfs`上に置かれ、環境を再作成した際に引き継がれません。`database/init.sql`から、常に同じ`items`テーブルと`42 | Item 42 | 4200`の1行を作成します。

## Go / Gin実装

Go / Gin実装は`apps/go-gin/`にあり、現在はGo 1.27.1、Gin 1.12.0、pgx/v5 5.10.0を使用します。server processは1つで、PostgreSQLのpool上限は10接続です。Docker ComposeではAPIコンテナを1 CPU・512 MBに制限し、非rootユーザー`65532:65532`で実行します。ポート`8080`はloopback interfaceだけに公開します。

```bash
docker compose up --detach --build --wait go-gin
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/json
curl http://127.0.0.1:8080/db/42
curl http://127.0.0.1:8080/cpu
make down
```

Goのformat、unit test、vet、コンテナ起動、API仕様、リソース制限、クリーンアップをまとめて確認するには、次を実行します。

```bash
make test-go-gin
```

## Go / Echo実装

Go / Echo実装は`apps/go-echo/`にあり、Go 1.27.1、Echo v5.3.1、pgx/v5 5.10.0を固定しています。Gin baselineとGo runtime・PostgreSQL driverを揃えたまま比較できるようにし、Gin側を暗黙にupgradeしていません。同じSQLとfixtureを使い、HTTP受付前にPostgreSQLへ接続し、pool上限は10接続です。

1つの`net/http` server processでEcho routerを提供します。比較と無関係なmiddleware、response cache、CPU処理の事前計算は追加せず、`/cpu`はrequestごとに直接再帰でFibonacci(30)を計算します。production imageにはstatic binaryだけを配置し、非rootの`65532:65532`で実行します。Composeから共通の1 CPU・512 MB、capability drop、no-new-privileges、loopback限定port公開、restart policyを継承します。

```bash
docker compose up --detach --build --wait go-echo
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/json
curl http://127.0.0.1:8080/db/42
curl http://127.0.0.1:8080/cpu
make down
make test-go-echo
```

`make test-go-echo`ではformat、unit tests、vet、production image、実PostgreSQL/API acceptance、BIGINT境界、起動失敗、SIGTERMでのgraceful shutdown、resource/process isolation、cleanupを確認します。共通contract suiteも変更せずEchoへ適用します。将来のGin対Echoの結果も、このリポジトリで固定した条件下のframework/routerを含むAPIスタック全体の比較であり、Goフレームワークの普遍的な順位を示すものではありません。

## Rust / Actix Web実装

Rust実装は`apps/rust-actix/`にあり、Rust 1.98.1、Actix Web 4.15.0、SQLx 0.9.0、Serde 1.0.228、serde_json 1.0.145を固定しています。推移的な依存も`Cargo.lock`で固定します。1つのActix workerでポート`8080`を受け付け、通常のSerde値からJSONを生成します。`/cpu`では毎request直接再帰でFibonacci(30)を計算します。SQLx poolはHTTP受付前にPostgreSQLへ接続し、上限は10接続です。

Dockerでは公開済みの`rust:1.98.0-bookworm`をdigest固定し、誤コンパイル修正を含むcompiler 1.98.1を明示導入して、`cargo +1.98.1 build --release --locked`でビルドします。実行用のDebian Bookworm slimもdigest固定し、release binaryのみをコピーして`65532:65532`で実行します。Cargoやソースコードは含めません。ComposeはPostgreSQLのhealthy状態を待ち、capabilities削除と権限昇格禁止、1 CPU・512 MB、loopback限定公開、restartなしを適用します。

```bash
docker compose up --detach --build --wait rust-actix
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/json
curl http://127.0.0.1:8080/db/42
curl http://127.0.0.1:8080/cpu
make down
make test-rust-actix
```

acceptance targetにはRustup、Python 3、Docker Compose v2、Makeが必要です。format、locked Rust tests、警告をエラーにするClippy、実DB・API、BIGINT境界、起動失敗、SIGTERM終了、container・network削除を検証します。各APIは同じホストポート`8080`を使うため、1つずつ起動してください。

## Rust / Axum実装

`apps/rust-axum/`はAxum 0.8.9とTokio 1.53.1を使います。既存のActix実装は変更せず、Rust 1.98.1、SQLx 0.9.0、Serde 1.0.228、serde_json 1.0.145、digest固定のbuilder・runtimeイメージを揃えています。推移的依存はcommitした`Cargo.lock`で固定します。

1つのserver processが明示的なTokio `current_thread` executorを使います。native Serde応答、共通のparameterized SQL、最大10接続のpool、requestごとの直接再帰によるFibonacci(30)を維持し、CPU offload、response cache、追加async workerは使いません。SIGINT/SIGTERMでは処理中のrequest完了を待ってからpoolを閉じます。非rootのrelease imageは共通の1 CPU・512 MiB制限を継承します。

```bash
make test-rust-axum                       # Rust検証と実PostgreSQL・container acceptance
make test-contract CONTRACT_IMPL=rust-axum # 変更しない共通contract
make axum-diagnostic                      # commit済みの作業ツリーで実行。結果は公開しない
```

port 8080を空け、各commandを順番に実行してください。Axum専用diagnosticは既存の固定済み負荷ツールとexternal readinessを使い、source・version情報と生データを`.cache/axum-diagnostic/`へ保存します。request errorやcleanup失敗を成功扱いせず、短縮profileの数値を公式結果として公開しません。通常CIのAxum jobで必須実行するため、一時的な開発workflowは不要です。実行方式、検証範囲、保存先の制約は[Axum実装・diagnosticガイド](AXUM.md)を参照してください。

## Node.js / Fastify実装

Node実装は`apps/node-fastify/`にあり、Node.js 24.20.0 LTS、Fastify 5.12.3、pg 8.23.0を使用します。直接依存と`package-lock.json`を固定し、公式の`node:24.20.0-bookworm-slim`イメージもdigestで固定します。再現性と保守性のため、LTSランタイムと安定版のFastify 5系を採用しています。

production modeでNode processを直接1つ起動し、PostgreSQLへの確認queryが成功してからHTTP接続を受け付けます。pool上限は10接続です。コンテナは非rootユーザー`node`で実行し、Linux capabilitiesを削除し、共通の1 CPU・512 MB制限を適用します。公開先は`127.0.0.1:8080`だけです。`/json`は通常のobjectをシリアライズし、`/cpu`は毎request直接再帰でFibonacci(30)を計算します。終了時はHTTP serverとpoolを閉じます。

各APIは同じローカルポートを使うため、1つずつ起動してください。

```bash
docker compose up --detach --build --wait node-fastify
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/json
curl http://127.0.0.1:8080/db/42
curl http://127.0.0.1:8080/cpu
make down
make test-node-fastify
```

`make test-node-fastify`にはNode.js 24.20.0、npm、Python 3、Docker Compose v2、Makeが必要です。focused tests、構文検証、image・API確認（実DBの更新・異常系を含む）、resource・process確認、正常終了、container・networkの削除を実行します。

## Python / FastAPI実装

Python実装は`apps/python-fastapi/`にあり、Python 3.14.7、FastAPI 0.141.1、Uvicorn 0.52.4、asyncpg 0.31.0を使用します。実行時依存と開発用依存は、バージョンとSHA256 hashを固定したlockファイルで管理します。Dockerの両stageは、index digestで固定した公式の`python:3.14.7-slim-bookworm`イメージを使用します。

Uvicornを直接1 workerで起動し、標準のasyncioイベントループとHTTP/1.1実装のh11を使用します。PostgreSQL接続確認後にHTTP受付を開始し、asyncpg poolの上限は10接続です。通常のPython値からJSONを生成し、signed BIGINTのIDも数値として正確に返します。`/cpu`は毎request直接再帰でFibonacci(30)を計算し、cacheや事前計算は使用しません。終了時はlifespanでpoolを閉じます。

productionコンテナは非rootユーザー`10001:10001`で実行し、testsと開発用依存を含めません。Linux capabilitiesを削除し、1 CPU・512 MBに制限します。ComposeはPostgreSQLのhealthy状態を待ち、`127.0.0.1:8080`だけに公開し、`/health`を確認します。自動restartは行いません。

```bash
docker compose up --detach --build --wait python-fastapi
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/json
curl http://127.0.0.1:8080/db/42
curl http://127.0.0.1:8080/cpu
make down
make test-python-fastapi PYTHON=python3.14
```

acceptance targetにはPOSIX環境のPython 3.14.7、Docker Compose v2、Makeが必要です。一時virtual environmentへhash検証付きで開発用依存をinstallし、Ruff、focused pytest tests、実Dockerサービス、DB更新・異常系、資源制限、1 worker、起動失敗、SIGTERM終了、container・network削除を確認します。Dockerを使わないfocused testsは[Contributing](../CONTRIBUTING.md)を参照してください。

## Java / Spring Boot実装

`apps/java-spring-boot/`はTemurin 25.0.4.1+1、Spring Boot 4.1.1、
Spring MVC / Tomcat、JDBC / HikariCP、チェックサムを検証するGradle 9.7.1を使用します。
共通のAPI、単一プロセス、1 CPU・512 MiB、DB接続上限10を維持します。
登録済みでCI対象ですが、Javaの公式測定結果はありません。
[Javaの登録と公式測定の区別](IMPLEMENTATIONS.md#java-registration-boundary-67)を参照してください。

```bash
make test-java-spring-boot
make test-contract CONTRACT_IMPL=java-spring-boot
```

受入テストには、POSIXホスト上の固定JDK、Python 3.10以降、Make、Docker Compose v2が必要です。
コンテナのみを使う共通契約テストには、ホストのJDKは不要です。
固定依存関係、起動・終了の検証、公式測定と分ける理由は
[Java実装ガイド](JAVA-SPRING-BOOT.md)を参照してください。

## 共通契約と公式運用

登録済みのすべての実装を、共通のAPI契約で検証できます。

```bash
make test-contract                       # 登録済みの実装を1つずつ順番に検証
make test-contract CONTRACT_IMPL=go-echo # 1実装を同じ契約で検証
```

HTTP status、JSONの内容・型、規定のerror response、応答の再現性を確認し、
失敗時にも分離された検証環境を片付けます。必要な環境、起動済みAPIのbase URLを指定する
方法、cleanupの制約は[共通contractの実行ガイド](../CONTRIBUTING.md#shared-contract-checks)を
参照してください。ローカルのbenchmark runnerは利用可能です。PRでは同じ検証と公開しない短縮benchmarkを実行します。
公式benchmarkは、性能に関わる変更を取り込んだ後、または再現性などの調査が必要な場合に、
[trusted mainで明示的に実行を依頼します](AUTOMATION.md#when-to-request-an-official-benchmark)。
週次実行や変更を検知しての自動計測は行いません。上流で新しいversionが公開されただけでは、
このリポジトリの固定versionは更新されません。手動起動後も、既存の検証済み結果の自動公開と
Pages反映まで実行するため、計測だけの操作ではありません。公開方式の見直しとmain保護は別途検討します。
現在の比較対象と初回公開の経緯は、[登録・比較グループガイド](IMPLEMENTATIONS.md#registered-and-measured-implementations)を参照してください。
結果更新には新しい完全な公式計測と検証が必要です。過去のレポートは書き換えません。

公式結果の監査・push成功後に、共通Pages workflowを直接呼び出します。[認可と復旧手順](AUTOMATION.md#github-pages)を参照してください。表示の復旧だけのために再計測する必要はありません。製品リリースは
[maintainerが明示的に実施する別の操作](RELEASING.md)であり、Pagesの副作用として作成しません。

## ローカルでの計測

変更をcommitした作業ツリー、Python 3.10以上、curl、ローカルのDocker Compose v2で実行します。

```bash
make benchmark
```

SHA256とversionを固定したoha 1.16.0を検証・導入し、APIを1つずつビルド・起動します。
共通contractの成功後、各endpointを規定条件でwarm-upし、3回ずつ計測します。
全計測とcleanupが成功した場合だけ、`results/latest.json`をatomicに保存します。
途中失敗では既存結果を保持します。生成ファイルはローカル結果であり、公式公開結果ではありません。

focused testsは`make test-benchmark`、短縮診断は`make benchmark-smoke`です。
短縮診断は`latest.json`を更新しません。必要環境、単位、結果形式、期限、メモリサンプリングの制約は
[実行・結果形式ガイド](BENCHMARK.md)を参照してください。
