package dev.simpleapibenchmark;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class FibonacciTest {
    @Test
    void followsTheDirectRecursionDefinition() {
        assertEquals(0, Fibonacci.calculate(0));
        assertEquals(1, Fibonacci.calculate(1));
        assertEquals(1, Fibonacci.calculate(2));
        assertEquals(55, Fibonacci.calculate(10));
        assertEquals(832040, Fibonacci.calculate(30));
        assertEquals(832040, Fibonacci.calculate(30));
    }
}
