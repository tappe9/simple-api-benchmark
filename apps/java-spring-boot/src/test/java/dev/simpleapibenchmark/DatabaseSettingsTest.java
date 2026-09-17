package dev.simpleapibenchmark;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;

class DatabaseSettingsTest {
    private static Map<String, String> environment() {
        return new HashMap<>(Map.of(
                "DATABASE_HOST", "postgres",
                "DATABASE_PORT", "5432",
                "DATABASE_NAME", "benchmark",
                "DATABASE_USER", "benchmark",
                "DATABASE_PASSWORD", "test-secret"));
    }

    @Test
    void validatesTheSharedEnvironmentWithoutEmbeddingCredentialsInTheUrl() {
        var settings = DatabaseSettings.fromEnvironment(environment());
        assertEquals("jdbc:postgresql://postgres:5432/benchmark", settings.jdbcUrl());
        assertEquals("benchmark", settings.user());
        assertEquals("test-secret", settings.password());
        assertFalse(settings.toString().contains("test-secret"));
    }

    @Test
    void missingSettingsFailWithSanitizedMessages() {
        for (String key : environment().keySet()) {
            var environment = environment();
            environment.remove(key);
            var error = assertThrows(IllegalArgumentException.class,
                    () -> DatabaseSettings.fromEnvironment(environment));
            assertFalse(error.toString().contains("test-secret"));
        }
    }

    @Test
    void malformedAddressAndPortCannotChangeJdbcConnectionProperties() {
        for (var change : Map.of(
                "DATABASE_HOST", "postgres/other?password=test-secret",
                "DATABASE_NAME", "benchmark?options=test-secret",
                "DATABASE_PORT", "65536").entrySet()) {
            var environment = environment();
            environment.put(change.getKey(), change.getValue());
            assertThrows(IllegalArgumentException.class,
                    () -> DatabaseSettings.fromEnvironment(environment));
        }
        for (String port : new String[] {"0", "-1", "abc", "5432junk", " 5432"}) {
            var environment = environment();
            environment.put("DATABASE_PORT", port);
            assertThrows(IllegalArgumentException.class,
                    () -> DatabaseSettings.fromEnvironment(environment));
        }
    }
}
