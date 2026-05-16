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

    // No SAFE401: manual try { ... } finally { ... } with close() in
    // the finally clause. Older idiom but still legal and accepted
    // by the rule (the heuristic can't statically prove the finally
    // closes the *specific* resource - it accepts the shape).
    public void safeManualClose(String path) throws IOException {
        FileInputStream in = new FileInputStream(path);
        try {
            in.read();
        } finally {
            in.close();
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
