package dev.simpleapibenchmark;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

class HealthcheckTest {
    @Test
    void acceptsOnlySuccessfulBoundedHealthJson() throws Exception {
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            String path = exchange.getRequestURI().getPath();
            int status = path.equals("/redirect") ? 302 : path.equals("/error") ? 503 : 200;
            String body = switch (path) {
                case "/invalid" -> "{\"status\":\"bad\"}";
                case "/large" -> "x".repeat(4096);
                default -> "{\"status\":\"ok\"}";
            };
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", path.equals("/html") ? "text/html" : "application/json");
            exchange.getResponseHeaders().set("Location", "/ok");
            exchange.sendResponseHeaders(status, bytes.length);
            try (var output = exchange.getResponseBody()) {
                output.write(bytes);
            }
        });
        server.start();
        String base = "http://127.0.0.1:" + server.getAddress().getPort();
        try {
            assertTrue(Healthcheck.check(URI.create(base + "/ok")));
            for (String path : new String[] {"/invalid", "/error", "/redirect", "/large", "/html"}) {
                assertFalse(Healthcheck.check(URI.create(base + path)), path);
            }
        } finally {
            server.stop(0);
        }
        assertFalse(Healthcheck.check(URI.create(base + "/ok")));
    }
}
