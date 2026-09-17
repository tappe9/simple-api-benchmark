package dev.simpleapibenchmark;

import java.sql.SQLException;
import java.util.List;
import java.util.regex.Pattern;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ApiController {
    private static final Pattern INTEGER = Pattern.compile("[+-]?[0-9]+");
    private final ItemRepository repository;

    public ApiController(ItemRepository repository) {
        this.repository = repository;
    }

    @GetMapping(value = "/health", produces = "application/json")
    public Health health() {
        return new Health("ok");
    }

    @GetMapping(value = "/json", produces = "application/json")
    public Message json() {
        return new Message("Hello, World!", List.of(1, 2, 3, 4, 5));
    }

    @GetMapping(value = "/cpu", produces = "application/json")
    public Cpu cpu() {
        return new Cpu(30, Fibonacci.calculate(30));
    }

    @GetMapping(value = "/db/{id}", produces = "application/json")
    public ResponseEntity<?> database(@PathVariable("id") String input) {
        final long id;
        try {
            if (!INTEGER.matcher(input).matches()) {
                return ResponseEntity.badRequest().body(new Error("invalid id"));
            }
            id = Long.parseLong(input);
        } catch (NumberFormatException invalid) {
            return ResponseEntity.badRequest().body(new Error("invalid id"));
        }
        try {
            var item = repository.find(id);
            if (item.isEmpty()) {
                return ResponseEntity.status(404).body(new Error("not found"));
            }
            return ResponseEntity.ok(item.get());
        } catch (SQLException failure) {
            return ResponseEntity.internalServerError().body(new Error("internal server error"));
        }
    }

    public record Health(String status) {}
    public record Message(String message, List<Integer> items) {}
    public record Cpu(int input, int result) {}
    public record Error(String error) {}
}
