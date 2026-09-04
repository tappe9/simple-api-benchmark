#!/usr/bin/env python3
"""Apply the Issue #4 Rust / Actix Web implementation after the RED run."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, content: str, *, executable: bool = False) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.strip() + "\n", encoding="utf-8")
    if executable:
        target.chmod(0o755)


write(
    "apps/rust-actix/Cargo.toml",
    r'''
[package]
name = "rust-actix"
version = "0.1.0"
edition = "2024"
rust-version = "1.98"
publish = false

[dependencies]
actix-web = { version = "=4.15.0", default-features = false, features = ["macros"] }
serde = { version = "=1.0.228", features = ["derive"] }
serde_json = "=1.0.145"
sqlx = { version = "=0.9.0", default-features = false, features = ["postgres", "runtime-tokio", "tls-none"] }

[profile.release]
codegen-units = 1
lto = "thin"
strip = "symbols"
''',
)

write(
    "apps/rust-actix/rust-toolchain.toml",
    r'''
[toolchain]
channel = "1.98.1"
profile = "minimal"
components = ["clippy", "rustfmt"]
''',
)

write(
    "apps/rust-actix/src/lib.rs",
    r'''
pub mod api;
pub mod database;
pub mod healthcheck;
pub mod item;
''',
)

write(
    "apps/rust-actix/src/item.rs",
    r'''
use crate::database::SELECT_ITEM_QUERY;
use serde::Serialize;
use sqlx::PgPool;
use std::{error::Error, fmt, future::Future, pin::Pin};

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Item {
    pub id: i64,
    pub name: String,
    pub price: i32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ItemStoreError;

impl fmt::Display for ItemStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("item store query failed")
    }
}

impl Error for ItemStoreError {}

pub type FindItemFuture<'a> =
    Pin<Box<dyn Future<Output = Result<Option<Item>, ItemStoreError>> + Send + 'a>>;

pub trait ItemStore: Send + Sync {
    fn find_by_id(&self, id: i64) -> FindItemFuture<'_>;
}

#[derive(Clone)]
pub struct SqlxItemStore {
    pool: PgPool,
}

impl SqlxItemStore {
    #[must_use]
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

impl ItemStore for SqlxItemStore {
    fn find_by_id(&self, id: i64) -> FindItemFuture<'_> {
        Box::pin(async move {
            let row = sqlx::query_as::<_, (i64, String, i32)>(SELECT_ITEM_QUERY)
                .bind(id)
                .fetch_optional(&self.pool)
                .await
                .map_err(|_| ItemStoreError)?;

            Ok(row.map(|(id, name, price)| Item { id, name, price }))
        })
    }
}
''',
)

write(
    "apps/rust-actix/src/database.rs",
    r'''
use sqlx::{
    PgPool,
    postgres::{PgConnectOptions, PgPoolOptions, PgSslMode},
};
use std::{env, error::Error, fmt, time::Duration};

pub const MAX_CONNECTIONS: u32 = 10;
pub const SELECT_ITEM_QUERY: &str = "SELECT id, name, price FROM items WHERE id = $1";
const ACQUIRE_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DatabaseConfig {
    pub host: String,
    pub port: u16,
    pub database: String,
    pub user: String,
    pub password: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DatabaseConfigError {
    MissingVariable(&'static str),
    InvalidPort(String),
}

impl fmt::Display for DatabaseConfigError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingVariable(name) => {
                write!(formatter, "required environment variable {name} is empty")
            }
            Self::InvalidPort(value) => write!(formatter, "DATABASE_PORT is invalid: {value:?}"),
        }
    }
}

impl Error for DatabaseConfigError {}

impl DatabaseConfig {
    pub fn from_environment() -> Result<Self, DatabaseConfigError> {
        let host = required_variable("DATABASE_HOST")?;
        let port_value = required_variable("DATABASE_PORT")?;
        let port = port_value
            .parse::<u16>()
            .map_err(|_| DatabaseConfigError::InvalidPort(port_value))?;

        Ok(Self {
            host,
            port,
            database: required_variable("DATABASE_NAME")?,
            user: required_variable("DATABASE_USER")?,
            password: required_variable("DATABASE_PASSWORD")?,
        })
    }

    #[must_use]
    pub fn connect_options(&self) -> PgConnectOptions {
        PgConnectOptions::new()
            .host(&self.host)
            .port(self.port)
            .database(&self.database)
            .username(&self.user)
            .password(&self.password)
            .ssl_mode(PgSslMode::Disable)
    }
}

fn required_variable(name: &'static str) -> Result<String, DatabaseConfigError> {
    match env::var(name) {
        Ok(value) if !value.is_empty() => Ok(value),
        _ => Err(DatabaseConfigError::MissingVariable(name)),
    }
}

pub async fn connect(config: &DatabaseConfig) -> Result<PgPool, sqlx::Error> {
    let pool = PgPoolOptions::new()
        .max_connections(MAX_CONNECTIONS)
        .acquire_timeout(ACQUIRE_TIMEOUT)
        .connect_with(config.connect_options())
        .await?;

    let connection = pool.acquire().await?;
    drop(connection);
    Ok(pool)
}

#[cfg(test)]
mod tests {
    use super::{DatabaseConfig, DatabaseConfigError, MAX_CONNECTIONS, SELECT_ITEM_QUERY};
    use std::{env, sync::Mutex};

    static ENVIRONMENT_LOCK: Mutex<()> = Mutex::new(());

    fn set_database_environment() {
        for (name, value) in [
            ("DATABASE_HOST", "postgres.internal"),
            ("DATABASE_PORT", "5433"),
            ("DATABASE_NAME", "benchmark"),
            ("DATABASE_USER", "benchmark-user"),
            ("DATABASE_PASSWORD", "local-test-value"),
        ] {
            // SAFETY: every mutation in this module is serialized by ENVIRONMENT_LOCK.
            unsafe { env::set_var(name, value) };
        }
    }

    #[test]
    fn database_config_reads_every_required_setting() {
        let _guard = ENVIRONMENT_LOCK.lock().expect("environment mutex poisoned");
        set_database_environment();

        let config = DatabaseConfig::from_environment().expect("configuration should be valid");

        assert_eq!(config.host, "postgres.internal");
        assert_eq!(config.port, 5433);
        assert_eq!(config.database, "benchmark");
        assert_eq!(config.user, "benchmark-user");
        assert_eq!(config.password, "local-test-value");
    }

    #[test]
    fn database_config_rejects_a_missing_setting() {
        let _guard = ENVIRONMENT_LOCK.lock().expect("environment mutex poisoned");
        set_database_environment();
        // SAFETY: every mutation in this module is serialized by ENVIRONMENT_LOCK.
        unsafe { env::remove_var("DATABASE_HOST") };

        let error = DatabaseConfig::from_environment().expect_err("missing host should fail");

        assert_eq!(
            error,
            DatabaseConfigError::MissingVariable("DATABASE_HOST")
        );
    }

    #[test]
    fn database_config_rejects_an_invalid_port() {
        let _guard = ENVIRONMENT_LOCK.lock().expect("environment mutex poisoned");
        set_database_environment();
        // SAFETY: every mutation in this module is serialized by ENVIRONMENT_LOCK.
        unsafe { env::set_var("DATABASE_PORT", "not-a-port") };

        let error = DatabaseConfig::from_environment().expect_err("invalid port should fail");

        assert_eq!(
            error,
            DatabaseConfigError::InvalidPort("not-a-port".to_owned())
        );
    }

    #[test]
    fn database_contract_uses_the_shared_limits_and_query() {
        assert_eq!(MAX_CONNECTIONS, 10);
        assert_eq!(
            SELECT_ITEM_QUERY,
            "SELECT id, name, price FROM items WHERE id = $1"
        );
    }
}
''',
)

write(
    "apps/rust-actix/src/api.rs",
    r'''
use crate::item::ItemStore;
use actix_web::{HttpResponse, web};
use serde::Serialize;
use std::sync::Arc;

const FIBONACCI_INPUT: u32 = 30;

#[derive(Clone)]
pub struct AppState {
    store: Arc<dyn ItemStore>,
}

impl AppState {
    #[must_use]
    pub fn new(store: Arc<dyn ItemStore>) -> Self {
        Self { store }
    }
}

#[derive(Serialize)]
struct HealthResponse {
    status: &'static str,
}

#[derive(Serialize)]
struct JsonResponse {
    message: &'static str,
    items: [u32; 5],
}

#[derive(Serialize)]
struct CpuResponse {
    input: u32,
    result: u64,
}

#[derive(Serialize)]
struct ErrorResponse {
    error: &'static str,
}

pub fn configure(configuration: &mut web::ServiceConfig) {
    configuration
        .route("/health", web::get().to(health))
        .route("/json", web::get().to(json))
        .route("/db/{id}", web::get().to(database))
        .route("/cpu", web::get().to(cpu));
}

async fn health() -> HttpResponse {
    HttpResponse::Ok().json(HealthResponse { status: "ok" })
}

async fn json() -> HttpResponse {
    HttpResponse::Ok().json(JsonResponse {
        message: "Hello, World!",
        items: [1, 2, 3, 4, 5],
    })
}

async fn database(path: web::Path<String>, state: web::Data<AppState>) -> HttpResponse {
    let Ok(id) = path.into_inner().parse::<i64>() else {
        return HttpResponse::BadRequest().json(ErrorResponse {
            error: "invalid id",
        });
    };

    match state.store.find_by_id(id).await {
        Ok(Some(item)) => HttpResponse::Ok().json(item),
        Ok(None) => HttpResponse::NotFound().json(ErrorResponse { error: "not found" }),
        Err(_) => HttpResponse::InternalServerError().json(ErrorResponse {
            error: "internal server error",
        }),
    }
}

async fn cpu() -> HttpResponse {
    HttpResponse::Ok().json(CpuResponse {
        input: FIBONACCI_INPUT,
        result: fibonacci(FIBONACCI_INPUT),
    })
}

fn fibonacci(n: u32) -> u64 {
    match n {
        0 => 0,
        1 => 1,
        _ => fibonacci(n - 1) + fibonacci(n - 2),
    }
}

#[cfg(test)]
mod tests {
    use super::{AppState, configure, fibonacci};
    use crate::item::{FindItemFuture, Item, ItemStore, ItemStoreError};
    use actix_web::{
        App,
        http::{StatusCode, header},
        test as actix_test, web,
    };
    use serde_json::{Value, json};
    use std::sync::{Arc, Mutex};

    #[derive(Clone)]
    struct StubStore {
        result: Result<Option<Item>, ItemStoreError>,
        calls: Arc<Mutex<Vec<i64>>>,
    }

    impl StubStore {
        fn new(result: Result<Option<Item>, ItemStoreError>) -> Self {
            Self {
                result,
                calls: Arc::new(Mutex::new(Vec::new())),
            }
        }
    }

    impl ItemStore for StubStore {
        fn find_by_id(&self, id: i64) -> FindItemFuture<'_> {
            self.calls.lock().expect("calls mutex poisoned").push(id);
            let result = self.result.clone();
            Box::pin(async move { result })
        }
    }

    async fn call(state: AppState, path: &str) -> (StatusCode, String, Value) {
        let service = actix_test::init_service(
            App::new()
                .app_data(web::Data::new(state))
                .configure(configure),
        )
        .await;
        let request = actix_test::TestRequest::get().uri(path).to_request();
        let response = actix_test::call_service(&service, request).await;
        let status = response.status();
        let content_type = response
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .unwrap_or_default()
            .to_owned();
        let body = actix_test::read_body(response).await;
        let payload = serde_json::from_slice(&body).expect("response body should be JSON");
        (status, content_type, payload)
    }

    fn state_with(
        result: Result<Option<Item>, ItemStoreError>,
    ) -> (AppState, Arc<Mutex<Vec<i64>>>) {
        let store = Arc::new(StubStore::new(result));
        let calls = Arc::clone(&store.calls);
        (AppState::new(store), calls)
    }

    fn assert_json_content_type(content_type: &str) {
        assert!(
            content_type.starts_with("application/json"),
            "unexpected Content-Type: {content_type:?}"
        );
    }

    #[actix_web::test]
    async fn health_endpoint_matches_the_contract() {
        let (state, calls) = state_with(Ok(None));
        let (status, content_type, payload) = call(state, "/health").await;

        assert_eq!(status, StatusCode::OK);
        assert_json_content_type(&content_type);
        assert_eq!(payload, json!({"status": "ok"}));
        assert!(calls.lock().expect("calls mutex poisoned").is_empty());
    }

    #[actix_web::test]
    async fn json_endpoint_matches_the_contract() {
        let (state, calls) = state_with(Ok(None));
        let (status, content_type, payload) = call(state, "/json").await;

        assert_eq!(status, StatusCode::OK);
        assert_json_content_type(&content_type);
        assert_eq!(
            payload,
            json!({"message": "Hello, World!", "items": [1, 2, 3, 4, 5]})
        );
        assert!(calls.lock().expect("calls mutex poisoned").is_empty());
    }

    #[actix_web::test]
    async fn database_endpoint_returns_the_queried_item() {
        let (state, calls) = state_with(Ok(Some(Item {
            id: 42,
            name: "Item 42".to_owned(),
            price: 4200,
        })));
        let (status, content_type, payload) = call(state, "/db/42").await;

        assert_eq!(status, StatusCode::OK);
        assert_json_content_type(&content_type);
        assert_eq!(payload, json!({"id": 42, "name": "Item 42", "price": 4200}));
        assert_eq!(*calls.lock().expect("calls mutex poisoned"), vec![42]);
    }

    #[actix_web::test]
    async fn database_endpoint_returns_not_found_for_an_unknown_id() {
        let (state, calls) = state_with(Ok(None));
        let (status, content_type, payload) = call(state, "/db/999").await;

        assert_eq!(status, StatusCode::NOT_FOUND);
        assert_json_content_type(&content_type);
        assert_eq!(payload, json!({"error": "not found"}));
        assert_eq!(*calls.lock().expect("calls mutex poisoned"), vec![999]);
    }

    #[actix_web::test]
    async fn database_endpoint_rejects_an_invalid_id_without_querying() {
        let (state, calls) = state_with(Err(ItemStoreError));
        let (status, content_type, payload) = call(state, "/db/not-an-integer").await;

        assert_eq!(status, StatusCode::BAD_REQUEST);
        assert_json_content_type(&content_type);
        assert_eq!(payload, json!({"error": "invalid id"}));
        assert!(calls.lock().expect("calls mutex poisoned").is_empty());
    }

    #[actix_web::test]
    async fn database_endpoint_hides_unexpected_store_errors() {
        let (state, calls) = state_with(Err(ItemStoreError));
        let (status, content_type, payload) = call(state, "/db/42").await;

        assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
        assert_json_content_type(&content_type);
        assert_eq!(payload, json!({"error": "internal server error"}));
        assert_eq!(*calls.lock().expect("calls mutex poisoned"), vec![42]);
    }

    #[actix_web::test]
    async fn cpu_endpoint_calculates_fibonacci_thirty_for_each_request() {
        let (state, calls) = state_with(Ok(None));
        let expected = json!({"input": 30, "result": 832040});

        let first = call(state.clone(), "/cpu").await;
        let second = call(state, "/cpu").await;

        assert_eq!(first.0, StatusCode::OK);
        assert_json_content_type(&first.1);
        assert_eq!(first.2, expected);
        assert_eq!(second.0, StatusCode::OK);
        assert_json_content_type(&second.1);
        assert_eq!(second.2, expected);
        assert!(calls.lock().expect("calls mutex poisoned").is_empty());
    }

    #[test]
    fn fibonacci_matches_the_documented_definition() {
        assert_eq!(fibonacci(0), 0);
        assert_eq!(fibonacci(1), 1);
        assert_eq!(fibonacci(2), 1);
        assert_eq!(fibonacci(10), 55);
        assert_eq!(fibonacci(30), 832040);
    }
}
''',
)

write(
    "apps/rust-actix/src/healthcheck.rs",
    r'''
use serde::Deserialize;
use std::{
    error::Error,
    fmt,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    time::Duration,
};

const HEALTHCHECK_TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Debug)]
pub struct HealthcheckError(String);

impl HealthcheckError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl fmt::Display for HealthcheckError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl Error for HealthcheckError {}

#[derive(Deserialize)]
struct HealthResponse {
    status: String,
}

pub fn check_health(address: &str) -> Result<(), HealthcheckError> {
    let socket = address
        .parse::<SocketAddr>()
        .map_err(|error| HealthcheckError::new(format!("invalid health address: {error}")))?;
    let mut stream = TcpStream::connect_timeout(&socket, HEALTHCHECK_TIMEOUT)
        .map_err(|error| HealthcheckError::new(format!("connect to health endpoint: {error}")))?;
    stream
        .set_read_timeout(Some(HEALTHCHECK_TIMEOUT))
        .map_err(|error| HealthcheckError::new(format!("set health read timeout: {error}")))?;
    stream
        .set_write_timeout(Some(HEALTHCHECK_TIMEOUT))
        .map_err(|error| HealthcheckError::new(format!("set health write timeout: {error}")))?;

    let request = format!(
        "GET /health HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|error| HealthcheckError::new(format!("write health request: {error}")))?;

    let mut response = Vec::new();
    stream
        .read_to_end(&mut response)
        .map_err(|error| HealthcheckError::new(format!("read health response: {error}")))?;
    validate_response(&response)
}

fn validate_response(response: &[u8]) -> Result<(), HealthcheckError> {
    let separator = response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| HealthcheckError::new("health response has no header separator"))?;
    let headers = std::str::from_utf8(&response[..separator])
        .map_err(|error| HealthcheckError::new(format!("health headers are not UTF-8: {error}")))?;
    let body = &response[separator + 4..];

    let mut lines = headers.split("\r\n");
    let status_line = lines
        .next()
        .ok_or_else(|| HealthcheckError::new("health response has no status line"))?;
    if !status_line.starts_with("HTTP/1.1 200 ") {
        return Err(HealthcheckError::new(format!(
            "unexpected health status line: {status_line:?}"
        )));
    }

    let is_json = lines.any(|line| {
        line.split_once(':').is_some_and(|(name, value)| {
            name.eq_ignore_ascii_case("content-type")
                && value
                    .trim()
                    .to_ascii_lowercase()
                    .starts_with("application/json")
        })
    });
    if !is_json {
        return Err(HealthcheckError::new(
            "health response Content-Type is not application/json",
        ));
    }

    let payload: HealthResponse = serde_json::from_slice(body)
        .map_err(|error| HealthcheckError::new(format!("decode health response: {error}")))?;
    if payload.status != "ok" {
        return Err(HealthcheckError::new(format!(
            "unexpected health payload status: {:?}",
            payload.status
        )));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::check_health;
    use std::{
        io::{BufRead, BufReader, Write},
        net::TcpListener,
        thread::{self, JoinHandle},
    };

    fn serve(response: &'static str) -> (String, JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test health server");
        let address = listener.local_addr().expect("read test server address");
        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept health request");
            let mut reader = BufReader::new(stream.try_clone().expect("clone test stream"));
            loop {
                let mut line = String::new();
                reader.read_line(&mut line).expect("read request line");
                if line == "\r\n" || line.is_empty() {
                    break;
                }
            }
            stream
                .write_all(response.as_bytes())
                .expect("write health response");
        });
        (address.to_string(), handle)
    }

    #[test]
    fn healthcheck_accepts_the_contract_response() {
        let (address, handle) = serve(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 15\r\nConnection: close\r\n\r\n{\"status\":\"ok\"}",
        );

        check_health(&address).expect("contract response should be healthy");
        handle.join().expect("health server should finish");
    }

    #[test]
    fn healthcheck_rejects_an_unhealthy_status() {
        let (address, handle) = serve(
            "HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: 15\r\nConnection: close\r\n\r\n{\"status\":\"no\"}",
        );

        let error = check_health(&address).expect_err("503 response should fail");
        assert!(error.to_string().contains("unexpected health status"));
        handle.join().expect("health server should finish");
    }

    #[test]
    fn healthcheck_rejects_an_unexpected_payload() {
        let (address, handle) = serve(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 15\r\nConnection: close\r\n\r\n{\"status\":\"no\"}",
        );

        let error = check_health(&address).expect_err("unexpected payload should fail");
        assert!(error.to_string().contains("unexpected health payload"));
        handle.join().expect("health server should finish");
    }
}
''',
)

write(
    "apps/rust-actix/src/main.rs",
    r'''
use actix_web::{App, HttpServer, web};
use rust_actix::{
    api::{self, AppState},
    database::{self, DatabaseConfig},
    healthcheck,
    item::SqlxItemStore,
};
use std::{env, io, sync::Arc};

const LISTEN_ADDRESS: &str = "0.0.0.0:8080";
const HEALTHCHECK_ADDRESS: &str = "127.0.0.1:8080";
const WORKERS: usize = 1;

#[actix_web::main]
async fn main() -> io::Result<()> {
    match (env::args().nth(1), env::args().nth(2)) {
        (None, None) => run_server().await,
        (Some(command), None) if command == "healthcheck" => healthcheck::check_health(
            HEALTHCHECK_ADDRESS,
        )
        .map_err(io::Error::other),
        _ => Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "usage: rust-actix [healthcheck]",
        )),
    }
}

async fn run_server() -> io::Result<()> {
    let config = DatabaseConfig::from_environment().map_err(io::Error::other)?;
    let pool = database::connect(&config).await.map_err(io::Error::other)?;
    let state = AppState::new(Arc::new(SqlxItemStore::new(pool)));

    HttpServer::new(move || {
        App::new()
            .app_data(web::Data::new(state.clone()))
            .configure(api::configure)
    })
    .workers(WORKERS)
    .bind(LISTEN_ADDRESS)?
    .run()
    .await
}

#[cfg(test)]
mod tests {
    use super::{HEALTHCHECK_ADDRESS, LISTEN_ADDRESS, WORKERS};

    #[test]
    fn server_uses_the_shared_runtime_contract() {
        assert_eq!(LISTEN_ADDRESS, "0.0.0.0:8080");
        assert_eq!(HEALTHCHECK_ADDRESS, "127.0.0.1:8080");
        assert_eq!(WORKERS, 1);
    }
}
''',
)

write(
    "apps/rust-actix/Dockerfile",
    r'''
FROM rust:1.98.1-bookworm AS build

WORKDIR /src
COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY src ./src
RUN cargo build --release --locked

FROM debian:bookworm-slim

COPY --from=build /src/target/release/rust-actix /usr/local/bin/rust-actix
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/rust-actix"]
''',
)

write(
    "tests/test_rust_actix_service.py",
    r'''
#!/usr/bin/env python3
"""Acceptance checks for the Rust / Actix Web API service."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
RUST_APP = ROOT / "apps" / "rust-actix"
COMPOSE_FILE = ROOT / "docker-compose.yml"
MAKEFILE = ROOT / "Makefile"
BASE_URL = "http://127.0.0.1:8080"


class CheckFailure(RuntimeError):
    """Raised when the Rust / Actix Web service violates its contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def run(
    command: Sequence[str],
    *,
    cwd: Path = ROOT,
    timeout: int = 300,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(command)}", flush=True)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise CheckFailure(f"required command is unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CheckFailure(
            f"command timed out after {timeout}s: {' '.join(command)}"
        ) from exc

    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(
            completed.stderr,
            end="" if completed.stderr.endswith("\n") else "\n",
            file=sys.stderr,
        )

    if check and completed.returncode != 0:
        raise CheckFailure(
            f"command exited with status {completed.returncode}: {' '.join(command)}"
        )
    return completed


def compose_service_block(compose: str, service: str) -> str:
    lines = compose.splitlines()
    marker = f"  {service}:"
    try:
        start = lines.index(marker)
    except ValueError as exc:
        raise CheckFailure(f"Compose service is missing: {service}") from exc

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line and not line.startswith(" "):
            end = index
            break
        if re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
            end = index
            break
    return "\n".join(lines[start:end])


def check_static_contract() -> None:
    required_files = (
        RUST_APP / "Cargo.toml",
        RUST_APP / "Cargo.lock",
        RUST_APP / "rust-toolchain.toml",
        RUST_APP / "Dockerfile",
        RUST_APP / "src" / "lib.rs",
        RUST_APP / "src" / "main.rs",
        RUST_APP / "src" / "api.rs",
        RUST_APP / "src" / "database.rs",
        RUST_APP / "src" / "healthcheck.rs",
        RUST_APP / "src" / "item.rs",
        COMPOSE_FILE,
        MAKEFILE,
    )
    for path in required_files:
        require(path.is_file(), f"required file is missing: {path.relative_to(ROOT)}")

    manifest = (RUST_APP / "Cargo.toml").read_text(encoding="utf-8")
    for dependency in (
        'actix-web = { version = "=4.15.0"',
        'serde = { version = "=1.0.228"',
        'serde_json = "=1.0.145"',
        'sqlx = { version = "=0.9.0"',
    ):
        require(dependency in manifest, f"dependency is not pinned: {dependency}")

    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    service = compose_service_block(compose, "rust-actix")
    require("context: ./apps/rust-actix" in service, "rust-actix build context is incorrect")
    require("condition: service_healthy" in service, "rust-actix does not wait for PostgreSQL health")
    require('127.0.0.1:8080:8080' in service, "rust-actix host port is not loopback-only")
    require(re.search(r"(?m)^    cpus: 1(?:\.0)?\s*$", service) is not None, "rust-actix CPU limit is not 1")
    require(re.search(r"(?m)^    mem_limit: 512m\s*$", service) is not None, "rust-actix memory limit is not 512 MB")
    require("/usr/local/bin/rust-actix" in service, "rust-actix health check is missing")

    dockerfile = (RUST_APP / "Dockerfile").read_text(encoding="utf-8")
    require("FROM rust:1.98.1-bookworm" in dockerfile, "Rust builder image is not version-pinned")
    require("cargo build --release --locked" in dockerfile, "release build is missing")
    require("FROM debian:bookworm-slim" in dockerfile, "runtime image is not Debian slim")
    require("USER 65532:65532" in dockerfile, "runtime does not use the non-root user")
    require(
        'ENTRYPOINT ["/usr/local/bin/rust-actix"]' in dockerfile,
        "runtime entrypoint is incorrect",
    )

    api_source = (RUST_APP / "src" / "api.rs").read_text(encoding="utf-8")
    compact_api = re.sub(r"\s+", "", api_source)
    require("fibonacci(n-1)+fibonacci(n-2)" in compact_api, "CPU implementation is not direct recursion")
    require("derive(Serialize)" in compact_api, "native Serde response types are missing")

    database_source = (RUST_APP / "src" / "database.rs").read_text(encoding="utf-8")
    require("MAX_CONNECTIONS: u32 = 10" in database_source, "database pool maximum is not 10")
    require("WHERE id = $1" in database_source, "database query is not parameterized")

    item_source = (RUST_APP / "src" / "item.rs").read_text(encoding="utf-8")
    require(".bind(id)" in item_source, "database ID is not bound as a query parameter")

    main_source = (RUST_APP / "src" / "main.rs").read_text(encoding="utf-8")
    require("const WORKERS: usize = 1" in main_source, "worker count is not fixed at one")
    require(".workers(WORKERS)" in main_source, "Actix worker count is not applied")

    makefile = MAKEFILE.read_text(encoding="utf-8")
    require(
        re.search(r"(?m)^test-rust-actix\s*:", makefile) is not None,
        "Makefile target is missing: test-rust-actix",
    )


def request_json(path: str, expected_status: int) -> dict[str, Any]:
    request = urllib.request.Request(f"{BASE_URL}{path}", method="GET")
    try:
        response = urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    except urllib.error.URLError as exc:
        raise CheckFailure(f"request failed for {path}: {exc}") from exc

    with response:
        status = response.status
        content_type = response.headers.get("Content-Type", "")
        body = response.read()

    require(status == expected_status, f"{path} returned status {status}, want {expected_status}")
    require(
        content_type.startswith("application/json"),
        f"{path} returned Content-Type {content_type!r}",
    )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise CheckFailure(f"{path} returned invalid JSON: {body!r}") from exc
    require(isinstance(payload, dict), f"{path} returned non-object JSON: {payload!r}")
    return payload


def check_endpoints() -> None:
    require(request_json("/health", 200) == {"status": "ok"}, "unexpected /health response")
    require(
        request_json("/json", 200)
        == {"message": "Hello, World!", "items": [1, 2, 3, 4, 5]},
        "unexpected /json response",
    )
    require(
        request_json("/db/42", 200) == {"id": 42, "name": "Item 42", "price": 4200},
        "unexpected /db/42 response",
    )
    require(
        request_json("/db/999", 404) == {"error": "not found"},
        "unexpected unknown-item response",
    )
    require(
        request_json("/db/not-an-integer", 400) == {"error": "invalid id"},
        "unexpected invalid-ID response",
    )
    expected_cpu = {"input": 30, "result": 832040}
    require(request_json("/cpu", 200) == expected_cpu, "unexpected /cpu response")
    require(request_json("/cpu", 200) == expected_cpu, "repeated /cpu response changed")


def check_container_contract() -> None:
    container_id = run(["docker", "compose", "ps", "--quiet", "rust-actix"]).stdout.strip()
    require(bool(container_id), "rust-actix container is not running")

    state = run(
        [
            "docker",
            "inspect",
            "--format",
            "{{.State.Health.Status}}|{{.RestartCount}}|{{.HostConfig.NanoCpus}}|{{.HostConfig.Memory}}|{{.Config.User}}",
            container_id,
        ]
    ).stdout.strip()
    require(
        state == "healthy|0|1000000000|536870912|65532:65532",
        f"unexpected rust-actix container configuration: {state!r}",
    )


def check_dynamic_contract() -> None:
    run(["cargo", "fmt", "--check"], cwd=RUST_APP)
    run(["cargo", "test", "--locked"], cwd=RUST_APP, timeout=600)
    run(
        [
            "cargo",
            "clippy",
            "--locked",
            "--all-targets",
            "--all-features",
            "--",
            "-D",
            "warnings",
        ],
        cwd=RUST_APP,
        timeout=600,
    )
    run(["docker", "compose", "config"])

    primary_error: BaseException | None = None
    try:
        run(
            [
                "docker",
                "compose",
                "up",
                "--detach",
                "--build",
                "--wait",
                "--wait-timeout",
                "240",
                "rust-actix",
            ],
            timeout=1200,
        )
        check_container_contract()
        check_endpoints()
    except BaseException as exc:
        primary_error = exc
    finally:
        cleanup = run(["make", "down"], check=False)
        remaining = run(
            ["docker", "compose", "ps", "-a", "--quiet"],
            check=False,
        )
        cleanup_error: CheckFailure | None = None
        if cleanup.returncode != 0:
            cleanup_error = CheckFailure(f"make down exited with status {cleanup.returncode}")
        elif remaining.returncode != 0:
            cleanup_error = CheckFailure(
                f"docker compose ps exited with status {remaining.returncode}"
            )
        elif remaining.stdout.strip():
            cleanup_error = CheckFailure(
                f"project containers remain after cleanup: {remaining.stdout.strip()}"
            )

        if primary_error is not None:
            if cleanup_error is not None:
                raise CheckFailure(f"{primary_error}; cleanup also failed: {cleanup_error}") from primary_error
            raise primary_error
        if cleanup_error is not None:
            raise cleanup_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--static",
        action="store_true",
        help="validate repository files without running Rust or Docker",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        check_static_contract()
        if not args.static:
            check_dynamic_contract()
    except CheckFailure as exc:
        print(f"Rust / Actix Web service check failed: {exc}", file=sys.stderr)
        return 1

    mode = "static contract" if args.static else "Rust / Actix Web service"
    print(f"{mode} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    executable=True,
)

compose_path = ROOT / "docker-compose.yml"
compose = compose_path.read_text(encoding="utf-8")
if "\n  rust-actix:\n" not in compose:
    rust_service = r'''

  rust-actix:
    build:
      context: ./apps/rust-actix
    environment:
      <<: *database-environment
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "127.0.0.1:8080:8080"
    healthcheck:
      test:
        - CMD
        - /usr/local/bin/rust-actix
        - healthcheck
      interval: 2s
      timeout: 3s
      retries: 30
      start_period: 5s
    cpus: 1.0
    mem_limit: 512m
    networks:
      - benchmark
    restart: "no"
'''
    marker = "\nnetworks:\n"
    if marker not in compose:
        raise RuntimeError("top-level Compose networks marker is missing")
    compose = compose.replace(marker, rust_service + marker, 1)
    compose_path.write_text(compose, encoding="utf-8")

makefile_path = ROOT / "Makefile"
makefile = makefile_path.read_text(encoding="utf-8")
phony_match = re.search(r"(?m)^\.PHONY: (?P<targets>.+)$", makefile)
if phony_match is None:
    raise RuntimeError("Makefile .PHONY declaration is missing")
targets = phony_match.group("targets").split()
if "test-rust-actix" not in targets:
    index = targets.index("down") if "down" in targets else len(targets)
    targets.insert(index, "test-rust-actix")
    makefile = (
        makefile[: phony_match.start("targets")]
        + " ".join(targets)
        + makefile[phony_match.end("targets") :]
    )
if not re.search(r"(?m)^test-rust-actix\s*:", makefile):
    marker = "test-go-gin:\n\t@$(PYTHON) tests/test_go_gin_service.py\n"
    if marker not in makefile:
        raise RuntimeError("test-go-gin Makefile target is missing")
    makefile = makefile.replace(
        marker,
        marker
        + "\n"
        + "test-rust-actix:\n"
        + "\t@$(PYTHON) tests/test_rust_actix_service.py\n",
        1,
    )
makefile_path.write_text(makefile, encoding="utf-8")
