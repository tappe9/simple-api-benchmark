package dev.simpleapibenchmark;

import java.sql.SQLException;
import java.util.Optional;
import javax.sql.DataSource;

final class JdbcItemRepository implements ItemRepository {
    private final DataSource dataSource;

    JdbcItemRepository(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @Override
    public Optional<Item> find(long id) throws SQLException {
        try (var connection = dataSource.getConnection();
                var statement = connection.prepareStatement(
                        "SELECT id, name, price FROM items WHERE id = ?")) {
            statement.setLong(1, id);
            statement.setQueryTimeout(3);
            try (var result = statement.executeQuery()) {
                if (!result.next()) {
                    return Optional.empty();
                }
                return Optional.of(new Item(result.getLong("id"), result.getString("name"),
                        result.getInt("price")));
            }
        }
    }
}
