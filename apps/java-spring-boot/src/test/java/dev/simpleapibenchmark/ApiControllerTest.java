package dev.simpleapibenchmark;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;

import java.sql.SQLException;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import tools.jackson.databind.json.JsonMapper;

class ApiControllerTest {
    private final JsonMapper json = JsonMapper.builder().build();
    private final Repository repository = new Repository();
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        mvc = MockMvcBuilders.standaloneSetup(new ApiController(repository)).build();
    }

    @Test
    void healthAndJsonFollowTheContract() throws Exception {
        response("/health", 200, "{\"status\":\"ok\"}");
        response("/json", 200, "{\"message\":\"Hello, World!\",\"items\":[1,2,3,4,5]}");
        assertEquals(0, repository.calls);
    }

    @Test
    void cpuComputesForRepeatedRequestsWithoutDatabaseAccess() throws Exception {
        for (int i = 0; i < 3; i++) {
            response("/cpu", 200, "{\"input\":30,\"result\":832040}");
        }
        assertEquals(0, repository.calls);
    }

    @Test
    void eachDatabaseRequestReadsTheRepositoryAgain() throws Exception {
        response("/db/42", 200, "{\"id\":42,\"name\":\"Item 42\",\"price\":4200}");
        repository.item = new Item(42, "Changed", 7);
        response("/db/42", 200, "{\"id\":42,\"name\":\"Changed\",\"price\":7}");
        assertEquals(2, repository.calls);
        assertEquals(42, repository.lastId);
    }

    @Test
    void missingRowsReturnTheDocumented404() throws Exception {
        repository.item = null;
        response("/db/999", 404, "{\"error\":\"not found\"}");
    }

    @ParameterizedTest
    @ValueSource(strings = {"invalid", "42junk", "1.0", "9223372036854775808", "-9223372036854775809", "--1", "１２", " 42"})
    void invalidIdsNeverReachTheRepository(String id) throws Exception {
        var result = mvc.perform(get("/db/{id}", id)).andReturn().getResponse();
        assertEquals(400, result.getStatus());
        assertEquals(json.readTree("{\"error\":\"invalid id\"}"), json.readTree(result.getContentAsString()));
        assertEquals(0, repository.calls);
    }

    @ParameterizedTest
    @ValueSource(longs = {Long.MIN_VALUE, Long.MAX_VALUE, 9007199254740993L, 0})
    void signedBigintBoundariesRemainJsonIntegers(long id) throws Exception {
        repository.item = new Item(id, "Boundary", 1);
        response("/db/" + id, 200, "{\"id\":" + id + ",\"name\":\"Boundary\",\"price\":1}");
        assertEquals(id, repository.lastId);
    }

    @Test
    void databaseFailuresAreSanitized() throws Exception {
        repository.fail = true;
        response("/db/42", 500, "{\"error\":\"internal server error\"}");
    }

    private void response(String path, int status, String expected) throws Exception {
        var result = mvc.perform(get(path)).andReturn().getResponse();
        assertEquals(status, result.getStatus());
        assertTrue(result.getContentType().startsWith("application/json"));
        assertEquals(json.readTree(expected), json.readTree(result.getContentAsString()));
    }

    private static final class Repository implements ItemRepository {
        private Item item = new Item(42, "Item 42", 4200);
        private int calls;
        private long lastId;
        private boolean fail;

        @Override
        public Optional<Item> find(long id) throws SQLException {
            calls++;
            lastId = id;
            if (fail) {
                throw new SQLException("secret-password: SELECT id FROM private_table");
            }
            return Optional.ofNullable(item);
        }
    }
}
