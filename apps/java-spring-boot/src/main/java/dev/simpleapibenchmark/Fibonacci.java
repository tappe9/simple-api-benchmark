package dev.simpleapibenchmark;

final class Fibonacci {
    private Fibonacci() {}

    static int calculate(int n) {
        if (n < 2) {
            return n;
        }
        return calculate(n - 1) + calculate(n - 2);
    }
}
