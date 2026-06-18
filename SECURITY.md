# Security policy

SafeLint is a static-analysis CLI that parses source code via Tree-sitter and walks the resulting trees. It does not execute the code it lints, make network requests, or open sockets. The threat surface is therefore narrow but not zero - see the [in-scope](#in-scope) section below for what counts as a vulnerability.

## Supported versions

Security fixes ship to the supported lines below. Older lines receive no security backports; the recommended action is to upgrade.

| Version line | Status |
|---|---|
| **2.5.x** (current; Go support) | ✅ Security fixes |
| **2.2.x - 2.4.x** (Rust support and later) | ✅ Security fixes through ~6 months after the next minor lands |
| **2.1.x** (Java + Spring Boot) | ❌ Upgrade to a current 2.x line |
| **2.0.x** (multi-language refactor) | ❌ Upgrade to a current 2.x line |
| **1.x** | ❌ Upgrade to 2.x |

A "minor" here is a `2.<N>.0` release (`2.0.0`, `2.1.0`, `2.2.0`, ...). RC versions on the active line get security fixes if they're still pre-GA at the time the report comes in.

## Reporting a vulnerability

**Please do not file public issues for security problems.** Use one of these private channels:

1. **GitHub's private vulnerability reporting** (preferred). Open <https://github.com/shelkesays/safelint/security/advisories/new>. Includes built-in CVE coordination and lets you attach proof-of-concept code without it being public until disclosure.
2. **Email**: `srahul07@gmail.com`. Subject prefix: `[safelint security]`. Include the same content listed below.

### What to include

For either channel, please include enough to confirm the issue and assess severity:

- safelint version (`safelint --version`).
- The reproduction case: a minimal repository tree, command line, or TOML config that demonstrates the issue.
- The observed behaviour (what bad thing happens) and the expected behaviour.
- Suspected severity and your reasoning (does it require attacker-controlled input? local-only or remote? privileges needed?).
- Your preferred disclosure timeline if you have one.
- A handle you'd like credited in the advisory, if you want credit.

### What happens next

- **Acknowledgement**: within 7 calendar days of receipt.
- **Initial assessment**: within 14 calendar days. Either "this is a vulnerability and we're working on a fix", "this isn't a vulnerability but here's why" (with rationale), or "we need more information to reproduce".
- **Fix and release**: as soon as practical. Severity-driven; a remote-code-execution-class bug ships out-of-cycle; a path-traversal in a rarely-used code path lands in the next regular release.
- **Disclosure**: coordinated, default 90 days from initial report or sooner if a fix ships earlier. Can be shortened by mutual agreement or extended if reasonable. CVE assignment is via GitHub Security Advisories.
- **Credit**: reporter is credited in the advisory and the CHANGELOG entry unless they ask to remain anonymous.

This is a single-maintainer project. Response times are best-effort but the timelines above are the commitment; if anything slips, you'll get a status update rather than silence.

## In scope

The following classes of issue are vulnerabilities for safelint:

- **Path traversal** in the `safelint skill install` flow. The install command creates files under `.claude/`, `.cursor/`, etc. (project scope) or `~/.claude/skills/safelint/` etc. (user scope). An attacker-controlled `--client` value, environment variable, or auto-detected marker path that allows writes outside those directories is in scope.
- **Arbitrary file write or read** via crafted TOML config. The `[tool.safelint.*]` config in `pyproject.toml` / `safelint.toml` is parsed with the stdlib `tomllib`. Any field whose value can escape to filesystem or network surface is in scope (e.g. a glob in `per_file_ignores` that traverses outside the project root and bypasses safety checks).
- **Code execution** in any form. safelint deliberately does not `eval` / `exec` / `subprocess` user code or config. If you find a path that does, that's in scope.
- **Bundled grammar tampering**. SafeLint depends on `tree-sitter`, `tree-sitter-python`, `tree-sitter-javascript`, `tree-sitter-typescript`, `tree-sitter-java`, `tree-sitter-rust`, and `tree-sitter-go` from PyPI. A typosquat or malicious dependency that ships through the published `safelint` package is in scope; report alongside the PyPI advisory mechanism if applicable.
- **Symlink races** in the install or skill-status flow. The skill-install logic creates symlinks when `--symlink` is passed; race-conditioned attacks that swap target files are in scope.
- **Privilege escalation** from the CLI's own permissions. safelint runs with the invoking user's permissions; any path that gains more than that is in scope.

If you're unsure whether something qualifies, report it - the cost of a false-positive report is small.

## Out of scope

These are not vulnerabilities for safelint. Please file them as regular issues if they bother you:

- **False positives or false negatives in lint rules.** Wrong rule decisions are bugs, not security issues. Open a normal issue with a code sample.
- **Denial of service / resource exhaustion.** Tree-sitter parsing can be made slow with pathological input, but safelint runs offline against the user's own source tree; the threat model doesn't include adversarial input. Report DoS-shaped issues as regular bugs if they're reproducible against realistic code.
- **Linting suspicious source code.** safelint's whole job is to ingest arbitrary source code; the source itself being malicious is a feature, not a vulnerability.
- **Memory or CPU consumption.** Python is memory-managed; resource exhaustion against the CLI process isn't a security boundary worth defending.
- **Stale results from the result cache.** The on-disk cache (`.safelint_cache/`) is keyed by file hash + config hash; stale entries are correctness bugs, not security issues.
- **Vulnerabilities in third-party dependencies that don't affect safelint's behaviour.** Outdated transitive deps in the lock file are tracked via Dependabot and get routine bumps; CVEs in deps that can't actually be triggered through safelint are not security issues for safelint specifically.

## Threat model

For context when assessing severity, safelint's runtime model:

- Reads `.py` / `.pyw` / `.js` / `.mjs` / `.cjs` / `.ts` / `.tsx` / `.as` / `.java` / `.rs` / `.go` files from the working directory tree.
- Reads `pyproject.toml` / `safelint.toml` from the project root (and parent directories walked for the config-discovery rule).
- Reads bundled skill files from the installed package's `skill_files/` directory.
- Writes violations to stdout / stderr (text, JSON, or SARIF format).
- For `safelint skill install`, writes a single skill file under a per-client directory (`.claude/skills/safelint/SKILL.md` etc.) at either project or user scope.
- For `safelint skill status / path / list`, only reads.

It does NOT:

- Execute the code it lints.
- Make any network requests.
- Open sockets.
- Read or write files outside the documented directories above.
- Run as a daemon or service.
- Accept input over any RPC channel.

The most realistic attacker profile is "someone trying to ship a malicious PR or dependency that uses safelint's parse phase as an attack vector against a developer's machine." That's the threat model the in-scope list is calibrated against.
