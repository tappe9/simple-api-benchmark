# Simple API Benchmark

[English](README.md) · [結果サイト](https://tappe9.github.io/simple-api-benchmark/)

**同じAPI・リソース上限・負荷設定で、APIスタック全体を比較します。**

Go・Rust・Node.js・Pythonの、小さく再現可能な比較です。
まず検証済みの結果を見るか、APIを1つローカルで試してみてください。

実装の登録、CI対象、公式の比較グループ、結果公開は、それぞれ別です。
現在の状態は[登録・比較グループガイド](docs/IMPLEMENTATIONS.md#registered-and-measured-implementations)を参照してください。
Java / Spring Bootは登録済みでCI対象ですが、[Issue #73](https://github.com/tappe9/simple-api-benchmark/issues/73)で公式比較への採用を保留しています。
[v0.1.0のリリース](docs/RELEASING.md)は、初期の4構成のスナップショットとして維持します。

## 結果

<!-- benchmark-results:start -->

計測完了（UTC）: `2026-09-28T00:35:06.995550+00:00`
Source: `c1d8e81b959e2c0ee0e5c4a1d8a7491790479f93` · [Actions run](https://github.com/tappe9/simple-api-benchmark/actions/runs/36360016510)
比較グループ: `eight-stack-v1` · 測定定義: `simple-api-v1` · API readiness: `external-readiness`

1 CPU・512 MiB・1 worker・DB pool 10・HTTP/1.1・50接続・warm-up 5秒・各endpointを30秒×3回。処理件数/秒が中央の1回から全指標を採用します。

### スループット比較

![JSONの処理件数/秒の比較](results/charts/json-throughput.svg)

![PostgreSQLの処理件数/秒の比較](results/charts/postgresql-throughput.svg)

![CPUの処理件数/秒の比較](results/charts/cpu-throughput.svg)

<details>
<summary>選択されたrunの全数値</summary>

| バックエンド | テスト | 処理件数/秒 ↑ | 平均応答 ms ↓ | 観測最大メモリ MiB ↓ |
| --- | --- | ---: | ---: | ---: |
| Go / Gin | JSON | 23,100.118 | 2.162 | 13.650 |
| Go / Gin | PostgreSQL | 10,657.985 | 4.687 | 16.890 |
| Go / Gin | CPU | 213.562 | 233.207 | 15.480 |
| Go / Echo | JSON | 23,339.013 | 2.140 | 12.880 |
| Go / Echo | PostgreSQL | 10,619.084 | 4.705 | 15.950 |
| Go / Echo | CPU | 214.397 | 232.189 | 13.980 |
| Rust / Actix Web | JSON | 51,019.909 | 0.978 | 2.941 |
| Rust / Actix Web | PostgreSQL | 9,147.483 | 5.461 | 4.469 |
| Rust / Actix Web | CPU | 326.751 | 152.534 | 4.602 |
| Rust / Axum | JSON | 49,008.469 | 1.018 | 3.578 |
| Rust / Axum | PostgreSQL | 9,412.448 | 5.308 | 4.520 |
| Rust / Axum | CPU | 322.449 | 154.625 | 4.605 |
| Node.js / Fastify | JSON | 14,224.888 | 3.512 | 40.160 |
| Node.js / Fastify | PostgreSQL | 6,493.631 | 7.694 | 51.270 |
| Node.js / Fastify | CPU | 90.275 | 548.936 | 51.290 |
| Node.js / Express | JSON | 8,338.420 | 5.993 | 43.960 |
| Node.js / Express | PostgreSQL | 4,829.482 | 10.347 | 47.340 |
| Node.js / Express | CPU | 94.794 | 522.991 | 47.390 |
| Python / FastAPI | JSON | 3,161.497 | 15.808 | 40.610 |
| Python / FastAPI | PostgreSQL | 1,768.623 | 28.255 | 42.360 |
| Python / FastAPI | CPU | 9.112 | 5,074.272 | 42.250 |
| Python / Flask | JSON | 1,848.743 | 27.030 | 58.770 |
| Python / Flask | PostgreSQL | 1,275.740 | 39.160 | 59.360 |
| Python / Flask | CPU | 9.164 | 5,045.261 | 59.180 |

</details>

↑ 多いほど高速、↓ 少ないほど良好です。各グラフはゼロ基準で、同一endpoint内の処理件数/秒だけを比較します。メモリはAPIコンテナだけの観測値で、PostgreSQLは含まず、短いピークを見逃す場合があります。共有GitHub-hosted環境でのAPIスタック全体の参考値であり、言語の普遍的な順位ではありません。

[Result JSON](results/latest.json) · [History](results/history/) · [Detailed results site](https://tappe9.github.io/simple-api-benchmark/) · [Methodology](docs/METHODOLOGY.md) · [Versions and conditions](results/latest.json)

<!-- benchmark-results:end -->

## 結果の読み方

各スタックは、同じ[API仕様](docs/API-CONTRACT.md)を実装します。

| エンドポイント | 処理 |
| --- | --- |
| `GET /json` | 小さなJSONを返す |
| `GET /db/42` | PostgreSQLから1行取得し、JSONで返す |
| `GET /cpu` | 直接再帰でFibonacci(30)を計算する |

`GET /health`は起動確認専用です。共通のリソース上限、DBのfixture、pool上限、負荷設定は
[測定方法](docs/METHODOLOGY.md)に記載しています。1つのserver processまたはworkerでも、
request threadの構成が同一とは限りません。計測前に契約テストを実行し、HTTPエラーや
タイムアウトのある結果を正常な公式結果として公開しません。

比較にはランタイム、HTTPサーバー、JSONライブラリ、DBドライバー、コンテナ設定も含まれます。
共有GitHub-hosted環境での計測で、メモリもAPIコンテナのサンプル値です。
ある回で速かったスタックが、言語やフレームワークの普遍的な順位を示すわけではありません。
表示されたsourceとprofileで一緒に計測した対象だけを比較し、新しい実装を過去のレポートに
挿入したり、存在しない値をゼロとして扱ったりしないでください。

## APIを1つ試す

このリポジトリをcloneし、ルートディレクトリで実行します。
起動済みのDocker daemon、BuildKitと`up --wait`に対応したDocker Compose v2、curlが必要です。
この例では、Go・Rust・Node.js・Python・Javaをホストへ入れる必要はありません。
ツールチェーンはイメージのビルドで用意します。`8080`ポートを空け、APIは1つずつ起動してください。

```bash
docker compose --project-name sab-example up --detach --build --wait go-gin
curl --fail http://127.0.0.1:8080/health
curl --fail http://127.0.0.1:8080/json
curl --fail http://127.0.0.1:8080/db/42
curl --fail http://127.0.0.1:8080/cpu
docker compose --project-name sab-example down --remove-orphans --volumes
```

Go / Ginと依存先のPostgreSQLが、固定fixtureで起動します。ホストへ公開するのはAPIのloopbackポートだけです。
最後のコマンドは**`sab-example`の全コンテナ、ネットワーク、孤立コンテナ、volumeを削除します**。
PostgreSQLはtmpfsを使うため、DBコンテナ停止時にローカルのデータは失われます。
このプロジェクト名は使い捨ての例専用にし、途中で中断した場合も同じcleanupを実行してください。
このHTTPアクセスは動作を試す例であり、ベンチマーク結果ではありません。

## 詳しいガイド

- [ローカル環境・実装の詳細・cleanup](docs/LOCAL-DEVELOPMENT.ja.md)
- [共通契約テスト](CONTRIBUTING.md#shared-contract-checks)と[コントリビューション](CONTRIBUTING.md)
- [ローカル計測と結果形式](docs/BENCHMARK.md)
- [公式benchmarkの実行依頼](docs/AUTOMATION.md#when-to-request-an-official-benchmark): 明示的な依頼でのみ起動し、監査済み結果の公開とPages反映まで行います
- [Pagesの認可・復旧手順](docs/AUTOMATION.md#github-pages): 表示の復旧だけのために再計測する必要はありません
- [アーキテクチャ](ARCHITECTURE.md) · [ロードマップ](ROADMAP.md) · [セキュリティ](SECURITY.md)

## ライセンス

[MIT](LICENSE)
