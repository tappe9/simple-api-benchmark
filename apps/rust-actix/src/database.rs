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

        assert_eq!(error, DatabaseConfigError::MissingVariable("DATABASE_HOST"));
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
