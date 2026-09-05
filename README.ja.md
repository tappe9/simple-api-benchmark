# Simple API Benchmark

[English](README.md)

**Go・Rust・Node.js・Pythonを、同じAPI・同じ制限・同じ負荷で比較します。**

Simple API Benchmarkは、4つのAPIスタックを同じエンドポイント、同じDockerリソース制限、同じベンチマーク設定で比較するOSSです。普遍的な最速言語を決めることではなく、誰でも理解できて、自分でも再実行できる小さな比較を目指します。

> **現在の状態:** v0.1を設計・実装中です。ベンチマーク結果はまだ公開していません。

## 比較対象

| 言語 | フレームワーク |
|---|---|
| Go | Gin |
| Rust | Actix Web |
| Node.js | Fastify |
| Python | FastAPI |

各実装は、同じ3つのベンチマーク用エンドポイントを提供します。

| テスト | エンドポイント | 簡単な説明 |
|---|---|---|
| JSON | `GET /json` | 小さなJSONを返す |
| PostgreSQL | `GET /db/42` | 1行取得してJSONで返す |
| CPU | `GET /cpu` | Fibonacci(30)を計算して返す |

`GET /health`は起動確認だけに使用します。

## 結果

v0.1の実装後、確認済みの最新結果を自動生成してここへ表示します。

| バックエンド | JSON 処理件数/秒 | PostgreSQL 処理件数/秒 | CPU 処理件数/秒 | 最大メモリ |
|---|---:|---:|---:|---:|
| Go / Gin | — | — | — | — |
| Rust / Actix Web | — | — | — | — |
| Node.js / Fastify | — | — | — | — |
| Python / FastAPI | — | — | — | — |

公開結果の見方:

- 1秒あたりの処理件数は、多いほど高速です。
- 平均応答時間は、短いほど高速です。詳細結果に表示します。
- 最大メモリは、少ないほど軽量です。
- 結果は、記載された測定環境での参考値です。

## 同じ条件

すべての実装で、次の条件を揃えます。

- 同じAPI仕様
- 同じ入力と期待する出力
- 同じCPU・メモリ制限
- 1つのserver processまたはworker
- 同じPostgreSQLデータ、SQL、pool上限
- 同じ負荷設定
- 各テストを3回実行し、中央の結果を表示

計測前にAPIの返却内容を自動確認します。HTTPエラーやタイムアウトが発生した結果は、正常な結果として公開しません。

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

Go実装は`apps/go-gin/`にあり、現在はGo 1.27.1、Gin 1.12.0、pgx/v5 5.10.0を使用します。server processは1つで、PostgreSQLのpool上限は10接続です。Docker ComposeではAPIコンテナを1 CPU・512 MBに制限し、非rootユーザー`65532:65532`で実行します。ポート`8080`はloopback interfaceだけに公開します。

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

acceptance targetにはPOSIX環境のPython 3.14.7、Docker Compose v2、Makeが必要です。一時virtual environmentへhash検証付きで開発用依存をinstallし、Ruff、focused pytest tests、実Dockerサービス、DB更新・異常系、資源制限、1 worker、起動失敗、SIGTERM終了、container・network削除を確認します。Dockerを使わないfocused testsは[Contributing](CONTRIBUTING.md)を参照してください。

4つのAPI実装を利用できます。共通contract suite、benchmark runner、恒久CIは今後の対象であり、性能測定結果はありません。

## 実行方法の目標

v0.1では、次の1コマンドで実行できる状態を目指します。

```bash
make benchmark
```

コンテナのビルド、API確認、ベンチマーク、`results/latest.json`の生成までを行います。

## ドキュメント

- [アーキテクチャ](ARCHITECTURE.md)
- [API仕様](docs/API-CONTRACT.md)
- [測定方法](docs/METHODOLOGY.md)
- [ロードマップ](ROADMAP.md)
- [コントリビューション](CONTRIBUTING.md)
- [セキュリティ](SECURITY.md)

## 重要な注意点

このプロジェクトが比較するのは、プログラミング言語単体ではなくAPIスタック全体です。結果には、フレームワーク、ランタイム、HTTPサーバー、JSONライブラリ、PostgreSQLドライバー、コンテナ設定の違いも含まれます。「今回の測定ではRust / Actix Webが最速だった」という結果は、「Rustは常に最速」という意味ではありません。

## ライセンス

[MIT](LICENSE)
