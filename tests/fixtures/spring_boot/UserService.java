package com.example.petclinic;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

// @Service fixture exercising SAFE902 (missing @Transactional on
// multi-write methods). Constructor-injected fields throughout to
// avoid SAFE901 noise.

@Service
public class UserService {

    private final UserRepository userRepo;
    private final AuditRepository auditRepo;

    public UserService(UserRepository userRepo, AuditRepository auditRepo) {
        this.userRepo = userRepo;
        this.auditRepo = auditRepo;
    }

    // SAFE902: two writes (userRepo.save + auditRepo.save) in a
    // @Service method without @Transactional - partial writes leak
    // on failure.
    public void registerUser(User user, AuditEvent audit) {
        userRepo.save(user);
        auditRepo.save(audit);
    }

    // No SAFE902: @Transactional on the method itself brackets the
    // two writes in one atomic transaction. The canonical safe
    // pattern for this rule.
    @Transactional
    public void registerUserSafe(User user, AuditEvent audit) {
        userRepo.save(user);
        auditRepo.save(audit);
    }

    // No SAFE902: single write is exempt from the rule. Spring
    // Data wraps single calls in their own transaction by default;
    // the rule only fires on 2+ writes.
    public void registerJustUser(User user) {
        userRepo.save(user);
    }

    // No SAFE902: this is a read-only method (no save / delete /
    // update calls), so the rule doesn't apply regardless of
    // @Transactional presence.
    public User findById(Long id) {
        return userRepo.findById(id).orElse(null);
    }

    public static class User {
        public Long id;
        public String name;
    }

    public static class AuditEvent {
        public Long userId;
        public String action;
    }

    public interface UserRepository {
        java.util.Optional<User> findById(Long id);
        User save(User u);
    }

    public interface AuditRepository {
        AuditEvent save(AuditEvent a);
    }
}
