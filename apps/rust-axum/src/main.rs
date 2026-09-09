use rust_axum::{
    api::{self, AppState},
    database::{self, DatabaseConfig},
    healthcheck,
    item::SqlxItemStore,
};
use sqlx::PgPool;
use std::{env, future::Future, io, sync::Arc};
use tokio::{net::TcpListener, signal::unix::{SignalKind, signal}};

const LISTEN_ADDRESS: &str = "0.0.0.0:8080";
const HEALTHCHECK_ADDRESS: &str = "127.0.0.1:8080";

#[tokio::main(flavor = "current_thread")]
async fn main() -> io::Result<()> {
    match (env::args().nth(1), env::args().nth(2)) {
        (None, None) => run_server().await,
        (Some(command), None) if command == "healthcheck" => {
            healthcheck::check_health(HEALTHCHECK_ADDRESS).map_err(io::Error::other)
        }
        _ => Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "usage: rust-axum [healthcheck]",
        )),
    }
}

async fn run_server() -> io::Result<()> {
    // Install both handlers before accepting connections; setup errors fail closed.
    let mut terminate = signal(SignalKind::terminate())?;
    let mut interrupt = signal(SignalKind::interrupt())?;
    let config = DatabaseConfig::from_environment().map_err(io::Error::other)?;
    let pool = database::connect(&config)
        .await
        .map_err(|_| io::Error::other("database connection failed"))?;
    let listener = match TcpListener::bind(LISTEN_ADDRESS).await {
        Ok(listener) => listener,
        Err(error) => {
            pool.close().await;
            return Err(error);
        }
    };
    let state = AppState::new(Arc::new(SqlxItemStore::new(pool.clone())));
    serve_until(listener, state, pool, async move {
            tokio::select! {
                _ = terminate.recv() => {},
                _ = interrupt.recv() => {},
            }
    }).await
}

async fn serve_until(
    _listener: TcpListener,
    _state: AppState,
    _pool: PgPool,
    _shutdown: impl Future<Output = ()> + Send + 'static,
) -> io::Result<()> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::serve_until;
    use rust_axum::{api::AppState, item::{FindItemFuture, Item, ItemStore}};
    use sqlx::postgres::PgPoolOptions;
    use std::{sync::Arc, time::Duration};
    use tokio::{
        io::{AsyncReadExt, AsyncWriteExt},
        net::{TcpListener, TcpStream},
        sync::{Notify, oneshot},
        time::timeout,
    };

    struct InFlightStore {
        started: Arc<Notify>,
        release: Arc<Notify>,
    }

    impl ItemStore for InFlightStore {
        fn find_by_id(&self, id: i64) -> FindItemFuture<'_> {
            Box::pin(async move {
                self.started.notify_one();
                self.release.notified().await;
                Ok(Some(Item { id, name: "in flight".to_owned(), price: 7 }))
            })
        }
    }

    #[tokio::test(flavor = "current_thread")]
    async fn shutdown_drains_an_in_flight_request_then_closes_the_pool() {
        timeout(Duration::from_secs(5), async {
            let listener = TcpListener::bind("127.0.0.1:0").await.expect("test listener");
            let address = listener.local_addr().expect("listener address");
            let started = Arc::new(Notify::new());
            let release = Arc::new(Notify::new());
            let state = AppState::new(Arc::new(InFlightStore {
                started: Arc::clone(&started),
                release: Arc::clone(&release),
            }));
            let pool = PgPoolOptions::new()
                .connect_lazy("postgres://benchmark:benchmark@127.0.0.1:1/benchmark")
                .expect("lazy pool");
            let (send, receive) = oneshot::channel();
            let server = tokio::spawn(serve_until(listener, state, pool.clone(), async move {
                receive.await.expect("shutdown sender");
            }));
            let mut client = TcpStream::connect(address).await.expect("HTTP client");
            client.write_all(b"GET /db/42 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                .await.expect("request write");
            started.notified().await;
            send.send(()).expect("shutdown signal");
            tokio::task::yield_now().await;
            assert!(!server.is_finished(), "shutdown must wait for the active request");
            release.notify_one();
            let mut bytes = Vec::new();
            client.read_to_end(&mut bytes).await.expect("response body");
            let response = String::from_utf8(bytes).expect("UTF-8 response");
            assert!(response.starts_with("HTTP/1.1 200"));
            assert!(response.contains("\"name\":\"in flight\""));
            server.await.expect("server task").expect("graceful shutdown");
            assert!(pool.is_closed(), "pool must be closed after the last request");
        }).await.expect("bounded in-flight shutdown");
    }
}
