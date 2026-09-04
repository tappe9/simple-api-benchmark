#[cfg(test)]
mod tests {
    use super::{DatabaseConfig, MAX_CONNECTIONS, SELECT_ITEM_QUERY};
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

    #[test]
    fn database_config_reads_every_required_setting() {
        let settings = settings();
        let config = DatabaseConfig::from_lookup(|key| {
            settings.get(key).copied().map(str::to_owned)
        })
        .expect("configuration should be valid");

        assert_eq!(config.host, "postgres.internal");
        assert_eq!(config.port, 5433);
        assert_eq!(config.database, "benchmark");
        assert_eq!(config.username, "benchmark-user");
        assert_eq!(config.password, "local-test-value");
    }

    #[test]
    fn database_config_rejects_a_missing_setting() {
        let mut settings = settings();
        settings.remove("DATABASE_HOST");

        let error = DatabaseConfig::from_lookup(|key| {
            settings.get(key).copied().map(str::to_owned)
        })
        .expect_err("missing host should fail");

        assert!(error.to_string().contains("DATABASE_HOST"));
    }

    #[test]
    fn database_config_rejects_an_empty_setting() {
        let mut settings = settings();
        settings.insert("DATABASE_NAME", "");

        let error = DatabaseConfig::from_lookup(|key| {
            settings.get(key).copied().map(str::to_owned)
        })
        .expect_err("empty database name should fail");

        assert!(error.to_string().contains("DATABASE_NAME"));
    }

    #[test]
    fn database_config_rejects_an_invalid_port() {
        let mut settings = settings();
        settings.insert("DATABASE_PORT", "not-a-port");

        let error = DatabaseConfig::from_lookup(|key| {
            settings.get(key).copied().map(str::to_owned)
        })
        .expect_err("invalid port should fail");

        assert!(error.to_string().contains("DATABASE_PORT"));
    }

    #[test]
    fn database_contract_uses_the_shared_pool_limit_and_query() {
        assert_eq!(MAX_CONNECTIONS, 10);
        assert_eq!(
            SELECT_ITEM_QUERY,
            "SELECT id, name, price FROM items WHERE id = $1"
        );
    }
}
