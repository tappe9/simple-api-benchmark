package dev.simpleapibenchmark;

import java.sql.SQLException;
import java.util.Optional;

@FunctionalInterface
public interface ItemRepository {
    Optional<Item> find(long id) throws SQLException;
}
