package dev.simpleapibenchmark;

import java.util.Map;

record DatabaseSettings(String jdbcUrl, String user, String password) {
    static DatabaseSettings fromEnvironment(Map<String, String> environment) {
        String host = required(environment, "DATABASE_HOST");
        String portText = required(environment, "DATABASE_PORT");
        String database = required(environment, "DATABASE_NAME");
        String user = required(environment, "DATABASE_USER");
        String password = required(environment, "DATABASE_PASSWORD");
        if (host.length() > 253 || !host.matches("[A-Za-z0-9.-]+")
                || !database.matches("[A-Za-z_][A-Za-z0-9_]*")
                || !portText.matches("[0-9]{1,5}")) {
            throw new IllegalArgumentException("invalid database address");
        }
        int port = Integer.parseInt(portText);
        if (port < 1 || port > 65535) {
            throw new IllegalArgumentException("invalid database port");
        }
        return new DatabaseSettings("jdbc:postgresql://" + host + ":" + port + "/" + database,
                user, password);
    }

    private static String required(Map<String, String> environment, String key) {
        String value = environment.get(key);
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("missing database configuration: " + key);
        }
        return value;
    }

    @Override
    public String toString() {
        return "DatabaseSettings[redacted]";
    }
}
