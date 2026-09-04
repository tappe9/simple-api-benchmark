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
        (Some(command), None) if command == "healthcheck" => {
            healthcheck::check_health(HEALTHCHECK_ADDRESS).map_err(io::Error::other)
        }
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
