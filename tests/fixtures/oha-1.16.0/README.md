# Real oha 1.16.0 output fixtures

These files are parser inputs, **not API benchmark results**. They were captured
from the official `oha-linux-amd64` asset with SHA256
`620bb9e16fb53eabc9a3fc45f88bdb41fefa3fee5c05e75892011ce320391716`.
The binary reported `oha 1.16.0` after checksum verification.

Capture: [development-input Actions run 33963099628](https://github.com/tappe9/simple-api-benchmark/actions/runs/33963099628),
2026-09-05, commit `535be9ca9f37a47108a2833a23778eb099553d81`.
The temporary capture workflow is retained in that commit's history, not main.

A Python `ThreadingHTTPServer` served HTTP/1.1 with an explicit Content-Length and
fixed `{"fixture":true}` body. `/error` returned 503. `/slow` delayed 0.2 seconds.
All commands used `--no-tui --output-format json --http-version 1.1 --redirect 0`:

| File | Additional arguments |
| --- | --- |
| `success.json` | `-n 20 -c 2 -t 2s http://127.0.0.1:18080/` |
| `timed.json` | `-z 1s -w -c 2 -t 2s http://127.0.0.1:18080/` |
| `http-error.json` | `-n 20 -c 2 -t 2s http://127.0.0.1:18080/error` |
| `timeout.json` | `-n 4 -c 2 -t 0.05s http://127.0.0.1:18080/slow` |

Fields and units were checked against upstream
[`src/printer.rs` at v1.16.0](https://github.com/hatoo/oha/blob/v1.16.0/src/printer.rs),
not inferred from metric names. Corrupt variants are created in tests without
changing these captured files. Updating oha requires new official checksums,
new actual fixtures, explicit parser review, and a documented baseline change.
