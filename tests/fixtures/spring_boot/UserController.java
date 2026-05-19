package com.example.petclinic;

import java.util.Map;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

// REST controller fixture exercising SAFE901 (field injection),
// SAFE903 (unvalidated @RequestBody), SAFE801 (SQL injection via
// JdbcTemplate.query, only fires under spring-boot preset), and
// SAFE803 (Map.get chained dereference). The constructor-injected
// JdbcTemplate field below is the recommended pattern - no SAFE901
// fires there, only on the @Autowired field.

@RestController
@RequestMapping("/users")
public class UserController {

    // SAFE901: @Autowired field injection - recommended fix is
    // constructor injection.
    @Autowired
    private UserService userService;

    // No SAFE901: constructor-injected. The @Autowired field above
    // is the violation marker; this final field is the control.
    private final JdbcTemplate jdbc;
    private final Map<Long, String> cache;

    public UserController(JdbcTemplate jdbc, Map<Long, String> cache) {
        this.jdbc = jdbc;
        this.cache = cache;
    }

    // No SAFE903: @PathVariable is deliberately excluded from the
    // rule (typically binds primitives where bean validation has
    // limited value).
    @GetMapping("/{id}")
    public User findById(@PathVariable Long id) {
        return userService.findOne(id);
    }

    // SAFE903: @RequestBody without @Valid or @Validated.
    @PostMapping
    public User create(@RequestBody UserDto dto) {
        return userService.persist(dto);
    }

    // No SAFE903: @RequestBody @Valid is the canonical safe pattern.
    @PutMapping
    public User update(@RequestBody @Valid UserDto dto) {
        return userService.merge(dto);
    }

    // SAFE801 fires under spring-boot preset: untrusted method
    // parameter ``name`` (every Java formal_parameter is seeded as
    // tainted) flows into jdbc.query() via string concatenation.
    // Under vanilla preset, ``query`` is NOT a recognised sink so
    // this does NOT fire.
    @GetMapping("/search")
    public Object search(@RequestParam String name) {
        String sql = "SELECT * FROM users WHERE name = '" + name + "'";
        return jdbc.query(sql, new Object[]{});
    }

    // SAFE803: cache.get(id) returns null on miss, immediately
    // dereferenced via .toString(). Fires under both vanilla and
    // spring-boot presets (``get`` is in the vanilla nullable list).
    @GetMapping("/{id}/name")
    public String getUserName(@PathVariable Long id) {
        return cache.get(id).toString();
    }

    public static class User {
        public Long id;
        public String name;
    }

    public static class UserDto {
        public String name;
    }

    public interface UserService {
        User findOne(Long id);
        User persist(UserDto dto);
        User merge(UserDto dto);
    }
}
