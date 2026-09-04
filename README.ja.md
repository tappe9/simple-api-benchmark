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

表の見方:

- 1秒あたりの処理件数は、多いほど高速です。
- 応答時間は、短いほど高速です。
- 最大メモリは、少ないほど軽量です。
- 結果は、記載された測定環境での参考値です。

## 同じ条件

すべての実装で、次の条件を揃えます。

- 同じAPI仕様
- 同じ入力と期待する出力
- 同じCPU・メモリ制限
- 同じPostgreSQLデータとSQL
- 同じ負荷設定
- 各テストを3回実行し、中央の結果を表示

計測前にAPIの返却内容を自動確認します。HTTPエラーやタイムアウトが発生した結果は、正常な結果として公開しません。

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
