package com.example.petclinic;

// Plain Java utility exercising SAFE102 (nesting_depth max 2) and
// SAFE104 (cyclomatic complexity max 10). The deepNested method
// below pushes both limits past the defaults; the flatHelper is the
// refactor target that avoids both.

public class ComplexNesting {

    // SAFE102 + SAFE104: nesting depth 4 (function > for > if > if)
    // and complexity well above 10 (multiple if / else if / ternary).
    public int deepNested(int[] grid) {
        int total = 0;
        for (int i = 0; i < grid.length; i++) {
            if (grid[i] > 0) {
                if (grid[i] % 2 == 0) {
                    total += grid[i] / 2;
                } else if (grid[i] % 3 == 0) {
                    total += grid[i] / 3;
                } else if (grid[i] % 5 == 0) {
                    total += grid[i] / 5;
                } else if (grid[i] % 7 == 0) {
                    total += grid[i] / 7;
                } else if (grid[i] % 11 == 0) {
                    total += grid[i] / 11;
                } else if (grid[i] % 13 == 0) {
                    total += grid[i] / 13;
                } else if (grid[i] % 17 == 0) {
                    total += grid[i] / 17;
                } else if (grid[i] % 19 == 0) {
                    total += grid[i] / 19;
                } else {
                    total += grid[i];
                }
            }
        }
        return total;
    }

    // No SAFE102 or SAFE104: early return + table-driven dispatch.
    // Demonstrates the canonical refactor for the rule. Nesting
    // depth 2, complexity 2.
    public int flatHelper(int[] grid) {
        if (grid == null) return 0;
        int total = 0;
        for (int v : grid) {
            total += scoreSingle(v);
        }
        return total;
    }

    private int scoreSingle(int v) {
        if (v <= 0) return 0;
        int[] divisors = {2, 3, 5, 7, 11, 13};
        for (int d : divisors) {
            if (v % d == 0) return v / d;
        }
        return v;
    }
}
