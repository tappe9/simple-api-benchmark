use sqlx::{
    PgPool,
    postgres::{PgConnectOptions, PgPoolOptions, PgSslMode},
};
use std::{env, error::Error, fmt, time::Duration};

pub const MAX_CONNECTIONS: u32 = 10;
pub const SELECT_ITEM_QUERY: &str = "SELECT id, name, price FROM items WHERE id = $1";
const ACQUIRE_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Clone, PartialEq, Eq)]
pub struct DatabaseConfig {
    pub host: String,
    pub port: u16,
    pub database: String,
    pub user: String,
    pub password: String,
}

#[derive(Clone, PartialEq, Eq)]
pub enum DatabaseConfigError {
    MissingVariable(&'static str),
    InvalidPort(String),
}

impl fmt::Debug for DatabaseConfig {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DatabaseConfig")
            .finish_non_exhaustive()
    }
}

impl fmt::Debug for DatabaseConfigError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self, formatter)
    }
}

impl fmt::Display for DatabaseConfigError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingVariable(name) => {
                write!(formatter, "required environment variable {name} is empty")
            }
            Self::InvalidPort(_) => formatter.write_str("DATABASE_PORT is invalid"),
        }
    }
}

impl Error for DatabaseConfigError {}

impl DatabaseConfig {
    pub fn from_environment() -> Result<Self, DatabaseConfigError> {
        Self::from_lookup(required_variable)
    }

    fn from_lookup(
        mut lookup: impl FnMut(&'static str) -> Result<String, DatabaseConfigError>,
    ) -> Result<Self, DatabaseConfigError> {
        let host = lookup("DATABASE_HOST")?;
        let port_value = lookup("DATABASE_PORT")?;
        let port = port_value
            .parse::<u16>()
            .map_err(|_| DatabaseConfigError::InvalidPort(port_value))?;

        Ok(Self {
            host,
            port,
            database: lookup("DATABASE_NAME")?,
            user: lookup("DATABASE_USER")?,
            password: lookup("DATABASE_PASSWORD")?,
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
    use std::collections::HashMap;

    fn settings() -> HashMap<&'static str, &'static str> {
        HashMap::from([
            ("DATABASE_HOST", "postgres.internal"),
            ("DATABASE_PORT", "5433"),
            ("DATABASE_NAME", "benchmark"),
            ("DATABASE_USER", "benchmark-user"),
            ("DATABASE_PASSWORD", "local-test-value"),
        ])
    }

    fn parse(values: &HashMap<&str, &str>) -> Result<DatabaseConfig, DatabaseConfigError> {
        DatabaseConfig::from_lookup(|name| {
            values
                .get(name)
                .filter(|value| !value.is_empty())
                .map(|value| (*value).to_owned())
                .ok_or(DatabaseConfigError::MissingVariable(name))
        })
    }

    #[test]
    fn database_config_reads_every_required_setting() {
        let config = parse(&settings()).expect("configuration should be valid");
        assert_eq!(config.host, "postgres.internal");
        assert_eq!(config.port, 5433);
        assert_eq!(config.database, "benchmark");
        assert_eq!(config.user, "benchmark-user");
        assert_eq!(config.password, "local-test-value");
    }

    #[test]
    fn database_config_rejects_every_missing_or_empty_setting() {
        for name in settings().keys() {
            let mut values = settings();
            values.remove(name);
            assert_eq!(
                parse(&values),
                Err(DatabaseConfigError::MissingVariable(name))
            );
            values.insert(name, "");
            assert_eq!(
                parse(&values),
                Err(DatabaseConfigError::MissingVariable(name))
            );
        }
    }

    #[test]
    fn database_config_rejects_an_invalid_port() {
        let mut values = settings();
        values.insert("DATABASE_PORT", "not-a-port");
        assert_eq!(
            parse(&values),
            Err(DatabaseConfigError::InvalidPort("not-a-port".to_owned()))
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
