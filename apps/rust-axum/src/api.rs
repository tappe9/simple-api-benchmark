use crate::item::ItemStore;
use axum::{
    Json, Router,
    extract::{Path, State, rejection::PathRejection},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
};
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

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/json", get(json))
        .route("/db/{id}", get(database))
        .route("/cpu", get(cpu))
        .with_state(state)
}

async fn health() -> Json<HealthResponse> {
    Json(HealthResponse { status: "ok" })
}

async fn json() -> Json<JsonResponse> {
    Json(JsonResponse {
        message: "Hello, World!",
        items: [1, 2, 3, 4, 5],
    })
}

fn error(status: StatusCode, message: &'static str) -> Response {
    (status, Json(ErrorResponse { error: message })).into_response()
}

async fn database(
    path: Result<Path<String>, PathRejection>,
    State(state): State<AppState>,
) -> Response {
    let Ok(Path(text)) = path else {
        return error(StatusCode::BAD_REQUEST, "invalid id");
    };
    let Ok(id) = text.parse::<i64>() else {
        return error(StatusCode::BAD_REQUEST, "invalid id");
    };
    match state.store.find_by_id(id).await {
        Ok(Some(item)) => Json(item).into_response(),
        Ok(None) => error(StatusCode::NOT_FOUND, "not found"),
        Err(_) => error(StatusCode::INTERNAL_SERVER_ERROR, "internal server error"),
    }
}

async fn cpu() -> Json<CpuResponse> {
    Json(CpuResponse {
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
    use super::{AppState, fibonacci, router};
    use crate::item::{FindItemFuture, Item, ItemStore, ItemStoreError};
    use axum::{
        body::{Body, to_bytes},
        http::{Request, StatusCode, header},
    };
    use serde_json::{Value, json};
    use std::sync::{Arc, Mutex};
    use tower::ServiceExt;

    struct StubStore {
        result: Result<Option<Item>, ItemStoreError>,
        calls: Arc<Mutex<Vec<i64>>>,
    }

    impl ItemStore for StubStore {
        fn find_by_id(&self, id: i64) -> FindItemFuture<'_> {
            self.calls.lock().expect("calls mutex").push(id);
            let result = self.result.clone();
            Box::pin(async move { result })
        }
    }

    fn state(result: Result<Option<Item>, ItemStoreError>) -> (AppState, Arc<Mutex<Vec<i64>>>) {
        let calls = Arc::new(Mutex::new(Vec::new()));
        let store = StubStore {
            result,
            calls: Arc::clone(&calls),
        };
        (AppState::new(Arc::new(store)), calls)
    }

    async fn expect(app: AppState, path: &str, status: StatusCode, payload: Value) {
        let response = router(app)
            .oneshot(
                Request::builder()
                    .uri(path)
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("router response");
        assert_eq!(response.status(), status, "{path}");
        assert_eq!(
            response.headers()[header::CONTENT_TYPE],
            "application/json",
            "{path}"
        );
        let body = to_bytes(response.into_body(), 65536)
            .await
            .expect("bounded body");
        let actual: Value = serde_json::from_slice(&body).expect("JSON body");
        assert_eq!(actual, payload, "{path}");
    }

    #[tokio::test(flavor = "current_thread")]
    async fn health_and_json_use_native_contract_responses_without_database_calls() {
        let (app, calls) = state(Err(ItemStoreError));
        expect(
            app.clone(),
            "/health",
            StatusCode::OK,
            json!({"status":"ok"}),
        )
        .await;
        expect(
            app,
            "/json",
            StatusCode::OK,
            json!({"message":"Hello, World!","items":[1,2,3,4,5]}),
        )
        .await;
        assert!(calls.lock().expect("calls").is_empty());
    }

    #[tokio::test(flavor = "current_thread")]
    async fn database_serializes_exact_signed_bigint_and_calls_store_every_time() {
        for id in [42, 9_007_199_254_740_993, i64::MAX, i64::MIN] {
            let item = Item {
                id,
                name: "item".to_owned(),
                price: -7,
            };
            let (app, calls) = state(Ok(Some(item)));
            for _ in 0..2 {
                expect(
                    app.clone(),
                    &format!("/db/{id}"),
                    StatusCode::OK,
                    json!({"id":id,"name":"item","price":-7}),
                )
                .await;
            }
            assert_eq!(*calls.lock().expect("calls"), [id, id]);
        }
    }

    #[tokio::test(flavor = "current_thread")]
    async fn integer_syntax_matches_the_existing_rust_baseline() {
        for (path, id) in [("+42", 42), ("00042", 42), ("0", 0), ("-1", -1)] {
            let (app, calls) = state(Ok(None));
            expect(
                app,
                &format!("/db/{path}"),
                StatusCode::NOT_FOUND,
                json!({"error":"not found"}),
            )
            .await;
            assert_eq!(*calls.lock().expect("calls"), [id]);
        }
    }

    #[tokio::test(flavor = "current_thread")]
    async fn invalid_identifiers_return_json_without_querying_the_database() {
        for path in [
            "text",
            "1.5",
            "1e1",
            "%2042",
            "42%20",
            "%EF%BC%94%EF%BC%92",
            "9223372036854775808",
            "-9223372036854775809",
            "42%20OR%201=1",
            "%FF",
        ] {
            let (app, calls) = state(Err(ItemStoreError));
            expect(
                app,
                &format!("/db/{path}"),
                StatusCode::BAD_REQUEST,
                json!({"error":"invalid id"}),
            )
            .await;
            assert!(calls.lock().expect("calls").is_empty());
        }
    }

    #[tokio::test(flavor = "current_thread")]
    async fn database_failures_return_a_sanitized_json_error() {
        let (app, calls) = state(Err(ItemStoreError));
        expect(
            app,
            "/db/42",
            StatusCode::INTERNAL_SERVER_ERROR,
            json!({"error":"internal server error"}),
        )
        .await;
        assert_eq!(*calls.lock().expect("calls"), [42]);
    }

    #[tokio::test(flavor = "current_thread")]
    async fn cpu_responses_match_the_contract_on_repeated_requests() {
        let (app, calls) = state(Err(ItemStoreError));
        for _ in 0..2 {
            expect(
                app.clone(),
                "/cpu",
                StatusCode::OK,
                json!({"input":30,"result":832040}),
            )
            .await;
        }
        assert!(calls.lock().expect("calls").is_empty());
    }

    #[test]
    fn fibonacci_obeys_the_recursive_definition() {
        for (input, expected) in [(0, 0), (1, 1), (2, 1), (10, 55), (30, 832040)] {
            assert_eq!(fibonacci(input), expected);
        }
    }
}
