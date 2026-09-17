package dev.simpleapibenchmark;

import com.zaxxer.hikari.HikariDataSource;
import java.sql.SQLException;
import javax.sql.DataSource;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
class DatabaseConfiguration {
    @Bean(destroyMethod = "close")
    HikariDataSource dataSource() {
        var settings = DatabaseSettings.fromEnvironment(System.getenv());
        var pool = new HikariDataSource();
        pool.setJdbcUrl(settings.jdbcUrl());
        pool.setUsername(settings.user());
        pool.setPassword(settings.password());
        pool.setPoolName("simple-api-java");
        pool.setMaximumPoolSize(10);
        pool.setMinimumIdle(0);
        pool.setConnectionTimeout(3000);
        pool.setValidationTimeout(1000);
        pool.setInitializationFailTimeout(3000);
        pool.addDataSourceProperty("ApplicationName", "simple-api-java");
        pool.addDataSourceProperty("connectTimeout", "3");
        pool.addDataSourceProperty("socketTimeout", "5");
        pool.addDataSourceProperty("cancelSignalTimeout", "2");
        try (var connection = pool.getConnection();
                var statement = connection.prepareStatement("SELECT 1")) {
            statement.setQueryTimeout(3);
            try (var result = statement.executeQuery()) {
                if (!result.next() || result.getInt(1) != 1) {
                    throw new SQLException("database readiness failed");
                }
            }
            return pool;
        } catch (SQLException | RuntimeException failure) {
            pool.close();
            throw new IllegalStateException("database startup failed");
        }
    }

    @Bean
    ItemRepository itemRepository(DataSource dataSource) {
        return new JdbcItemRepository(dataSource);
    }
}
