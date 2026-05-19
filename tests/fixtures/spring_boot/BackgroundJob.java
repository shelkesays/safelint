package com.example.petclinic;

import java.util.concurrent.CompletableFuture;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

// @Async fixture exercising SAFE904 (checked exceptions on @Async
// methods get swallowed silently by Spring's thread-pool executor).
// One method per pattern: unsafe (throws), safe-internal (catches),
// safe-future (returns CompletableFuture.failedFuture).

@Component
public class BackgroundJob {

    // SAFE904: @Async method declares a throws clause. Spring runs
    // this on a separate thread and silently swallows the
    // InterruptedException; the caller never sees it.
    @Async
    public void runUnsafe() throws InterruptedException {
        Thread.sleep(1000);
    }

    // No SAFE904: @Async without a throws clause (the recommended
    // pattern). The exception is caught + logged internally.
    @Async
    public void runSafe() {
        try {
            Thread.sleep(1000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    // No SAFE904: @Async returning CompletableFuture. Exceptions
    // are surfaced via CompletableFuture.failedFuture; the
    // declared throws clause is also absent so the rule doesn't
    // fire.
    @Async
    public CompletableFuture<Void> runFutureBased() {
        try {
            Thread.sleep(1000);
            return CompletableFuture.completedFuture(null);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return CompletableFuture.failedFuture(e);
        }
    }

    // No SAFE904: method has a throws clause BUT is not annotated
    // @Async, so the rule doesn't apply. The caller will see the
    // exception synchronously.
    public void runSync() throws InterruptedException {
        Thread.sleep(1000);
    }
}
