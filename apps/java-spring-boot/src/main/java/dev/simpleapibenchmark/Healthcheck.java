package dev.simpleapibenchmark;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/** A small standalone probe; it does not start Spring or connect to PostgreSQL. */
public final class Healthcheck {
    private Healthcheck() {}

    static boolean check(URI address) {
        HttpURLConnection connection = null;
        long deadline = System.nanoTime() + 1_500_000_000L;
        try {
            connection = (HttpURLConnection) address.toURL().openConnection();
            connection.setConnectTimeout(500);
            connection.setReadTimeout(500);
            connection.setInstanceFollowRedirects(false);
            if (connection.getResponseCode() != 200) {
                return false;
            }
            String contentType = connection.getContentType();
            if (contentType == null
                    || !contentType.split(";", 2)[0].trim().toLowerCase(Locale.ROOT)
                            .equals("application/json")) {
                return false;
            }
            try (var input = connection.getInputStream();
                    var output = new ByteArrayOutputStream()) {
                for (int count = 0; count <= 1024; count++) {
                    if (System.nanoTime() >= deadline) {
                        return false;
                    }
                    int value = input.read();
                    if (value == -1) {
                        return output.toString(StandardCharsets.UTF_8)
                                .matches("\\s*\\{\\s*\"status\"\\s*:\\s*\"ok\"\\s*}\\s*");
                    }
                    output.write(value);
                }
                return false;
            }
        } catch (IOException | IllegalArgumentException failure) {
            return false;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    public static void main(String[] args) {
        System.exit(check(URI.create("http://127.0.0.1:8080/health")) ? 0 : 1);
    }
}
