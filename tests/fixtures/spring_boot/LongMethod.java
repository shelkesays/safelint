package com.example.petclinic;

// Plain Java utility exercising SAFE101 (function_length max 60
// lines). The expandedSwitch method below clears the cap; the
// dispatch method below it shows the refactor.

public class LongMethod {

    // SAFE101: this method runs ~70 lines, above the default max
    // of 60. Tree-sitter counts source lines including blanks
    // inside the function body.
    public String expandedSwitch(int code) {
        if (code == 1) {
            return "one";
        }
        if (code == 2) {
            return "two";
        }
        if (code == 3) {
            return "three";
        }
        if (code == 4) {
            return "four";
        }
        if (code == 5) {
            return "five";
        }
        if (code == 6) {
            return "six";
        }
        if (code == 7) {
            return "seven";
        }
        if (code == 8) {
            return "eight";
        }
        if (code == 9) {
            return "nine";
        }
        if (code == 10) {
            return "ten";
        }
        if (code == 11) {
            return "eleven";
        }
        if (code == 12) {
            return "twelve";
        }
        if (code == 13) {
            return "thirteen";
        }
        if (code == 14) {
            return "fourteen";
        }
        if (code == 15) {
            return "fifteen";
        }
        if (code == 16) {
            return "sixteen";
        }
        if (code == 17) {
            return "seventeen";
        }
        if (code == 18) {
            return "eighteen";
        }
        if (code == 19) {
            return "nineteen";
        }
        if (code == 20) {
            return "twenty";
        }
        return "unknown";
    }

    // No SAFE101: same logic, ~12 lines via a switch expression.
    // Demonstrates the canonical refactor.
    public String compactSwitch(int code) {
        return switch (code) {
            case 1 -> "one";
            case 2 -> "two";
            case 3 -> "three";
            case 4 -> "four";
            case 5 -> "five";
            default -> "unknown";
        };
    }
}
