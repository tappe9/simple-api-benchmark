#[cfg(test)]
mod tests {
    use super::{configure, fibonacci, AppState};
    use crate::item::{FindItemFuture, Item, ItemStore, ItemStoreError};
    use actix_web::{
        http::{header, StatusCode},
        test, web, App,
    };
    use serde_json::{json, Value};
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
        let service = test::init_service(
            App::new()
                .app_data(web::Data::new(state))
                .configure(configure),
        )
        .await;
        let request = test::TestRequest::get().uri(path).to_request();
        let response = test::call_service(&service, request).await;
        let status = response.status();
        let content_type = response
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .unwrap_or_default()
            .to_owned();
        let body = test::read_body(response).await;
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
