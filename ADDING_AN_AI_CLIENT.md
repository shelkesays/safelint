# Adding a new AI client to SafeLint

This guide is the cheat sheet for adding support for a new AI coding client (GitHub Copilot, codex, windsurf, antigravity, etc.) to SafeLint's `safelint skill install` command. The architecture was built for this — the moving parts you need to understand and the steps you need to follow are below.

> [!NOTE]
> Today Claude Code and Cursor are registered. Adding a new client is a one-`ClientSpec` change plus a bundled artefact and tests. No control-flow changes elsewhere — install / detection / CLI choices / output all read from the registry.

For the user-facing surface (auto-detection logic, how each client is invoked after install, troubleshooting), see [`AI_CLIENTS.md`](AI_CLIENTS.md). This file is for contributors *adding* a new entry to the registry.

## The architecture, in five sentences

1. `safelint._skill_install.ClientSpec` is a frozen dataclass holding everything the engine needs about an AI client: detection markers, install destination, bundled artefact location, output wording.
2. Adding a client = appending one `ClientSpec` instance to `_CLIENT_SPECS` and shipping the bundled artefact under `src/safelint/skill_files/`.
3. The auto-detection scanner walks the registry in order, looking for each spec's `cwd_markers` (then `home_markers` if cwd is empty) — the matching specs drive the install.
4. The install primitives (`_install_copy`, `_install_symlink`, `_install_symlink_directory_filtered`) are client-agnostic — they handle file vs. directory sources from the spec's `bundled_relpath` without caring which client it's for.
5. CLI `--client` choices on both `install` and `path` subcommands are derived from the registry, so argparse stays in sync automatically the moment a new spec lands.

## Step-by-step: adding hypothetical "Windsurf" support

### 1. Decide on the bundled artefact shape

Two shapes are supported today:

| Shape | Example | Bundle layout |
|---|---|---|
| **Single file** | Cursor's `.mdc` | `src/safelint/skill_files/<client>/<filename>` |
| **Directory tree** | Claude Code's skill folder | `src/safelint/skill_files/` (root, with peer-client subdirs excluded) |

Most agents read a single instructions / rules file (the easier shape). Only Claude Code currently uses a directory tree because its skill format requires a `SKILL.md` plus per-language addendums.

For Windsurf, assume single-file like Cursor: `src/safelint/skill_files/windsurf/safelint-rules.md`.

### 2. Write the bundled artefact

Adapt the existing `SKILL.md` content into the new client's native format. The workflow is the same across clients (verify install → identify language → run with `--format json` → parse → present); only frontmatter and file shape differ.

For Windsurf (assume it uses Markdown with no frontmatter):

```bash
cp src/safelint/skill_files/cursor/safelint.mdc src/safelint/skill_files/windsurf/safelint-rules.md
```

Then strip Cursor's MDC frontmatter (the `--- description: ... ---` block) and tweak any client-specific phrasing. The `--- name: safelint description: ... ---` from Claude's `SKILL.md` is also a starting point if you want frontmatter.

Keep the workflow body language-neutral — language addendums under `skill_files/languages/` are shared rather than duplicated. The new client's instructions should tell its agent how to find them via `safelint skill path` if it needs them.

### 3. Append a `ClientSpec` entry

In `src/safelint/_skill_install.py`, define the spec and add it to the registry:

```python
_WINDSURF_SPEC = ClientSpec(
    name="windsurf",                       # CLI value: --client windsurf
    display_name="Windsurf",                # User-facing label in messages
    artefact_label="rules",                 # Output noun: "skill" / "rule" / "rules" / "instructions"
    cwd_markers=(".windsurfrules", ".codeium"),  # cwd paths that signal "this client is used here"
    home_markers=(".codeium",),             # home paths that signal "this client is installed"
    install_relpath=(".windsurfrules",),     # path components from scope root
    bundled_relpath=("windsurf", "safelint-rules.md"),  # path components under skill_files/
    restart_hint="Reload Windsurf (or restart the editor) to pick up the new rules.",
    usage_hint='Then ask Windsurf "run safelint" or "lint with safelint".',
)


_CLIENT_SPECS: tuple[ClientSpec, ...] = (_CLAUDE_SPEC, _CURSOR_SPEC, _WINDSURF_SPEC)
```

Field reference:

| Field | Purpose |
|---|---|
| `name` | CLI value passed to `--client`. Lowercase, alphanumeric, no spaces. |
| `display_name` | Human label used in detection notices and success messages (e.g. *"safelint: Windsurf rules copied to ..."*). |
| `artefact_label` | Output noun for the artefact — used in *"{display_name} {artefact_label} copied to ..."*. Pick whatever reads naturally: "skill", "rule", "rules", "instructions". |
| `cwd_markers` | Tuple of relative paths under cwd that signal "this client is used in this project". Detection iterates in order, stops at the first match, surfaces it in the notice. Choose well-known paths users actually have (e.g. config dirs / files Windsurf creates) — avoid generic markers that might appear in unrelated projects. |
| `home_markers` | Same idea, for the home-directory fallback. Typically the user-global config directory for the client. |
| `install_relpath` | Where the artefact gets installed, relative to scope root (cwd for project-scope, home for user-scope). Tuple of path components — `(".windsurfrules",)` means a single file at `<scope>/.windsurfrules`; `(".claude", "skills", "safelint")` means a directory at `<scope>/.claude/skills/safelint/`. |
| `bundled_relpath` | Where the source artefact lives under `skill_files/`. Tuple of path components. Use `()` (empty tuple) for the whole `skill_files/` root (Claude pattern). |
| `restart_hint` | Printed after a successful install — tells the user how to make the AI client pick up the new artefact. |
| `usage_hint` | Printed after `restart_hint` — tells the user what to say to the agent next. |

### 4. (Optional) Update peer-client exclusion

If your bundle lives under `skill_files/<client>/` and is *not* part of the Claude skill bundle (i.e. it's a per-client peer like Cursor's MDC), add the directory name to `_PEER_CLIENT_DIRS`:

```python
_PEER_CLIENT_DIRS: frozenset[str] = frozenset({"cursor", "windsurf"})
```

This excludes your bundle from the Claude directory-tree install (both copy and symlink modes) so it doesn't leak into `~/.claude/skills/safelint/` where it doesn't belong.

You only skip this step when the new client is single-file at the `skill_files/` root, or when it shares the Claude bundle. For typical "single-file under `skill_files/<client>/`" additions, always add to `_PEER_CLIENT_DIRS`.

### 5. Wire up file extensions in `pyproject.toml`

If your bundled artefact uses a file extension that isn't already in the package-data glob, extend it. Example for a `.txt` artefact:

```toml
[tool.setuptools.package-data]
safelint = [
    "py.typed",
    "skill_files/**/*.md",
    "skill_files/**/*.mdc",
    "skill_files/**/*.txt",   # ← new
]
```

Without this, the file won't be included in the wheel — `safelint skill install` would fail at `_spec_bundled_source`.

### 6. Add tests

In `tests/test_skill_install.py`, mirror the structure of the Cursor tests:

```python
def test_bundled_windsurf_artefact_exists_in_wheel() -> None:
    """The Windsurf rules ship alongside other skills under skill_files/windsurf/."""
    path = _skill_install.bundled_skill_path() / "windsurf" / "safelint-rules.md"
    assert path.is_file()


def test_install_windsurf_copy_user_scope(monkeypatch, tmp_path, capsys):
    """``--client windsurf`` copies the bundled rules to ~/.windsurfrules."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="windsurf"))
    assert rc == 0
    assert (home / ".windsurfrules").is_file()


def test_install_windsurf_copy_project_scope(monkeypatch, tmp_path):
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="windsurf", project=True))
    assert rc == 0
    assert (cwd / ".windsurfrules").is_file()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_windsurf_symlink_user_scope(monkeypatch, tmp_path):
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="windsurf", symlink=True))
    assert rc == 0
    target = home / ".windsurfrules"
    assert target.is_symlink()


def test_install_auto_detects_windsurf_in_cwd(monkeypatch, tmp_path, capsys):
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / ".windsurfrules").write_text("rules", encoding="utf-8")
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (cwd / ".windsurfrules").is_file()
    out = capsys.readouterr().out
    assert "Windsurf (.windsurfrules)" in out


def test_cli_routes_skill_install_with_windsurf_client(monkeypatch, mocker):
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "windsurf"])
    spy = mocker.patch.object(_skill_install, "run_install", return_value=0)
    with pytest.raises(SystemExit):
        cli.main()
    args = spy.call_args.args[0]
    assert args.client == "windsurf"
```

The existing Cursor tests are a good template — copy them and substitute paths / markers.

### 7. Update documentation

Three places to touch:

1. **[`AI_CLIENTS.md`](AI_CLIENTS.md)** — add a row to the *Supported clients* table; add a *Per-client guides* subsection (markers, install location, how to invoke after install); update the *Roadmap* section so the new client is no longer there.
2. **[`src/safelint/skill_files/README.md`](src/safelint/skill_files/README.md)** — extend the supported-clients list at the top; update the install examples if the new client has a non-obvious setup.
3. **[`CHANGELOG.md`](CHANGELOG.md)** — add an entry under the next release section announcing the support.

### 8. Run the pipeline

```bash
uv run pytest -q
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run ty check src/
uv run safelint check src/
```

All five must pass. The new tests should bring overall coverage in line with the existing 97% threshold.

## Choosing detection markers

Three things to look for:

1. **A file or directory the AI client *creates* automatically** when the user opts into it on a given project — these are reliable "yes this client is in use here" signals.
2. **Don't overload generic paths.** `.config/` would match too many things; `.codeium/` is specific.
3. **Multiple markers are fine.** If the client uses both a file (`.windsurfrules`) and a directory (`.codeium/`), include both — detection iterates in order and picks the first match.

The detection notice surfaces whichever marker actually fired (e.g. *"detected Windsurf (.windsurfrules)"*) so users can see which signal triggered the install.

## Choosing the install destination

Whatever location the AI client *natively* reads its skill / rules / instructions from. Examples:

| Client | Install destination |
|---|---|
| Claude Code | `~/.claude/skills/<skill_name>/` (user) or `<cwd>/.claude/skills/<skill_name>/` (project) |
| Cursor | `~/.cursor/rules/<rule>.mdc` (user) or `<cwd>/.cursor/rules/<rule>.mdc` (project) |
| Windsurf (hypothetical) | `~/.windsurfrules` (user) or `<cwd>/.windsurfrules` (project) |

The user shouldn't need to configure the client to find safelint's install — it should "just work" because the install lands where the client looks by default.

## Submission checklist

Before opening a pull request:

- [ ] New `ClientSpec` entry added to `_CLIENT_SPECS` in `src/safelint/_skill_install.py`
- [ ] Bundled artefact lives under `src/safelint/skill_files/<client>/`
- [ ] Peer-client exclusion (`_PEER_CLIENT_DIRS`) updated if applicable
- [ ] `pyproject.toml` package-data glob covers any new file extension
- [ ] Tests added: bundled-file existence, copy/symlink user/project, force replace, CLI routing, auto-detection
- [ ] Pipeline green: `pytest`, `ruff check`, `ruff format --check`, `ty check`, `safelint check src/` all clean at >=97% coverage
- [ ] Documentation updated: `AI_CLIENTS.md`, `src/safelint/skill_files/README.md`, `CHANGELOG.md`
- [ ] PR description includes a screenshot or transcript of `safelint skill install --client <new>` succeeding on a fresh project

## Things to avoid

- **Don't add an "auto-install everything" branch that bypasses `_resolve_install_plan`.** The two-tier (cwd → home) detection is the contract; new clients plug into it via `cwd_markers` / `home_markers`, not by routing around it.
- **Don't hardcode client checks in print helpers.** All output flows through the spec — adding `if client == "windsurf"` branches inside `_print_install_success` defeats the registry pattern.
- **Don't depend on the AI client itself being installed during testing.** Tests redirect `Path.home()` / `Path.cwd()` and create fake markers; the real client doesn't need to exist on the test machine.
- **Don't break backwards compatibility for existing clients.** New entries should be additive — if you find yourself wanting to change `_CLAUDE_SPEC`, that's a separate change with its own discussion.

## See also

- [`AI_CLIENTS.md`](AI_CLIENTS.md) — user-facing guide for using the AI client integrations
- [`src/safelint/_skill_install.py`](src/safelint/_skill_install.py) — the registry implementation
- [`tests/test_skill_install.py`](tests/test_skill_install.py) — the test patterns to mirror
- [`ADDING_A_LANGUAGE.md`](ADDING_A_LANGUAGE.md) — adding a new language to safelint itself (a different kind of extension)
