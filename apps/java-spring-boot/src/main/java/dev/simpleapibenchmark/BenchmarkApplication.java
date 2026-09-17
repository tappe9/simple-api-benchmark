package dev.simpleapibenchmark;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication(proxyBeanMethods = false)
public class BenchmarkApplication {
    public static void main(String[] args) {
        try {
            SpringApplication.run(BenchmarkApplication.class, args);
        } catch (Exception failure) {
            // Configuration and driver exceptions may contain credentials or SQL.
            System.err.println("application startup failed");
            System.exit(1);
        }
    }
}
