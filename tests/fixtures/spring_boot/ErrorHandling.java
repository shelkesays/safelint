package com.example.petclinic;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

// Plain Java utility exercising SAFE202 (empty_except) and SAFE203
// (logging_on_error). The unsafe methods below trigger the rules;
// the safe methods show the canonical fixes.

public class ErrorHandling {

    private static final Logger logger = LoggerFactory.getLogger(ErrorHandling.class);

    // SAFE202: empty catch block - the typical "swallow and continue"
    // anti-pattern.
    public void swallowExceptionEmpty() {
        try {
            riskyCall();
        } catch (Exception e) {
            // intentionally empty
        }
    }

    // SAFE202: comment-only catch is also empty (tree-sitter-java
    // emits comments as named children of blocks).
    public void swallowExceptionWithComment() {
        try {
            riskyCall();
        } catch (Exception e) {
            // TODO: handle this later
        }
    }

    // SAFE203: catch block missing a logging call. The body has
    // statements but none are recognised loggers.
    public void catchWithoutLogging() {
        try {
            riskyCall();
        } catch (Exception e) {
            int dummy = 42;
            System.out.println("caught: " + dummy);
        }
    }

    // No SAFE202 / SAFE203: SLF4J logger.error(...) call recognised
    // as a logging method. The canonical safe pattern.
    public void catchWithLogging() {
        try {
            riskyCall();
        } catch (Exception e) {
            logger.error("riskyCall failed", e);
        }
    }

    // No SAFE202 / SAFE203: re-raising the caught exception
    // (throw e where e matches the catch-parameter binding) is
    // recognised as legitimate handling - the exception continues
    // up the stack, no logging required at this level.
    public void catchAndRethrow() throws Exception {
        try {
            riskyCall();
        } catch (Exception e) {
            throw e;
        }
    }

    private void riskyCall() throws Exception {
        throw new Exception("boom");
    }
}
