package com.example.petclinic;

import java.io.BufferedReader;
import java.io.FileInputStream;
import java.io.FileReader;
import java.io.IOException;

// Plain Java utility (no Spring annotations) exercising SAFE401
// (resource_lifecycle). Java's idiom is try-with-resources for any
// AutoCloseable; the classic try { ... } finally { close(); } is
// accepted too. Each method below is one pattern.

public class ResourceUsage {

    // SAFE401: FileInputStream opened outside try-with-resources
    // and outside a try/finally with explicit close().
    public void leakStream(String path) throws IOException {
        FileInputStream in = new FileInputStream(path);
        in.read();
        // Resource leaks if read() throws.
    }

    // No SAFE401: try-with-resources is the canonical safe pattern.
    public void safeWithResources(String path) throws IOException {
        try (FileInputStream in = new FileInputStream(path)) {
            in.read();
        }
    }

    // No SAFE401: canonical pre-Java-7 manual try / finally with the
    // acquirer INSIDE the try block (so the rule's parent walk sees the
    // try_statement ancestor and accepts it). The null-init dance
    // ensures the variable is visible in finally even though the
    // acquirer is scoped to try. Older idiom but still legal and
    // accepted by the rule. (The acquirer-OUTSIDE-try pattern -
    // ``FileInputStream in = new FileInputStream(p); try { ... }
    // finally { in.close(); }`` - is genuinely unguarded under this
    // heuristic and would correctly fire SAFE401; that's not the
    // pattern we want to demonstrate as safe.)
    public void safeManualClose(String path) throws IOException {
        FileInputStream in = null;
        try {
            in = new FileInputStream(path);
            in.read();
        } finally {
            if (in != null) {
                in.close();
            }
        }
    }

    // SAFE401: nested resource also fires when the outer is in
    // try-with-resources but the inner is not.
    public void leakInnerResource(String path) throws IOException {
        try (BufferedReader outer = new BufferedReader(new FileReader(path))) {
            FileReader inner = new FileReader(path);
            inner.read();
            // inner is never closed.
        }
    }
}
