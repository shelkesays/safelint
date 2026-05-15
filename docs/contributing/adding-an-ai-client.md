# Adding a new AI client to SafeLint

This guide is the cheat sheet for adding support for a new AI coding client (GitHub Copilot, codex, windsurf, antigravity, etc.) to SafeLint's `safelint skill install` command. The architecture was built for this, the moving parts you need to understand and the steps you need to follow are below.

!!! note

    Twelve clients are registered today (Claude Code, Cursor, GitHub Copilot, Gemini, Windsurf, codex, Continue.dev, Cline, aider, Trae, Antigravity, Zed). Adding the next is a one-`ClientSpec` change plus a bundled artefact and tests. No control-flow changes elsewhere, install / detection / CLI choices / output all read from the registry.

For the user-facing surface (auto-detection logic, how each client is invoked after install, troubleshooting), see [AI client integrations](../ai-clients/index.md). This file is for contributors *adding* a new entry to the registry.

## The architecture, in five sentences

1. `safelint._skill_install.ClientSpec` is a frozen dataclass holding everything the engine needs about an AI client: detection markers, install destination, bundled artefact location, output wording.
2. Adding a client = appending one `ClientSpec` instance to `_CLIENT_SPECS` and shipping the bundled artefact under `src/safelint/skill_files/`.
3. The auto-detection scanner walks the registry in order, looking for each spec's `cwd_markers` (then `home_markers` if cwd is empty), the matching specs drive the install.
4. The install primitives (`_install_copy`, `_install_symlink`, `_install_symlink_directory_filtered`) are client-agnostic, they handle file vs. directory sources from the spec's `bundled_relpath` without caring which client it's for.
5. CLI `--client` choices on both `install` and `path` subcommands are derived from the registry, so argparse stays in sync automatically the moment a new spec lands.

## Step-by-step: adding a new client

> The walkthrough below uses *Windsurf* as a worked example because it has a clean, single-file rules convention. Windsurf is now actually shipped (since v1.11.0), feel free to compare this guide against the real implementation in `_skill_install.py` (`_WINDSURF_SPEC`) for cross-reference.

### 1. Decide on the bundled artefact shape

Every client today installs a **single file** under a per-client subdirectory of the bundle: `src/safelint/skill_files/<client>/<filename>`. Claude Code is `claude/SKILL.md`, Cursor is `cursor/safelint.mdc`, Windsurf would be `windsurf/safelint-rules.md`, and so on. The shared `languages/` and `README.md` at the bundle root are looked up on demand by every client via `safelint skill path`.

For Windsurf the bundled artefact lives at `src/safelint/skill_files/windsurf/safelint-rules.md`.

### 2. Write the bundled artefact

Adapt the existing `claude/SKILL.md` content into the new client's native format. The workflow is the same across clients (verify install → identify language → run with `--format json` → parse → present); only frontmatter and file shape differ.

For Windsurf (assume it uses Markdown with no frontmatter):

```bash
cp src/safelint/skill_files/cursor/safelint.mdc src/safelint/skill_files/windsurf/safelint-rules.md
```

Then strip Cursor's MDC frontmatter (the `--- description: ... ---` block) and tweak any client-specific phrasing. The `--- name: safelint description: ... ---` block at the top of `claude/SKILL.md` is also a starting point if you want frontmatter.

Keep the workflow body language-neutral, language addendums under `skill_files/languages/` are shared rather than duplicated. The new client's instructions should tell its agent how to find them via `safelint skill path` if it needs them.

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
| `artefact_label` | Output noun for the artefact, used in *"{display_name} {artefact_label} copied to ..."*. Pick whatever reads naturally: "skill", "rule", "rules", "instructions". |
| `cwd_markers` | Tuple of relative paths under cwd that signal "this client is used in this project". Detection iterates in order, stops at the first match, surfaces it in the notice. Choose well-known paths users actually have (e.g. config dirs / files Windsurf creates), avoid generic markers that might appear in unrelated projects. |
| `home_markers` | Same idea, for the home-directory fallback. Typically the user-global config directory for the client. |
| `install_relpath` | Where the artefact gets installed, relative to scope root (cwd for project-scope, home for user-scope). Tuple of path components; every client today installs a single file, e.g. `(".windsurfrules",)` for Windsurf, `(".cursor", "rules", "safelint.mdc")` for Cursor, `(".claude", "skills", "safelint", "SKILL.md")` for Claude Code. |
| `bundled_relpath` | Where the source artefact lives under `skill_files/`. Tuple of path components pointing at a single file, e.g. `("windsurf", "safelint-rules.md")`. |
| `restart_hint` | Printed after a successful install, tells the user how to make the AI client pick up the new artefact. |
| `usage_hint` | Printed after `restart_hint`, tells the user what to say to the agent next. |
| `documentation_relpaths` | Tuple of relpaths under `skill_files/` whose combined text *must* mention every rule code/name in `ALL_RULES` and every extension in `supported_extensions()`. Drift-detection tests parametrised over `_CLIENT_SPECS` enforce this, a new rule or language without corresponding bundled-doc updates fails CI. For a single-file client whose bundled artefact lives at `skill_files/windsurf/safelint-rules.md`, set this to `(("windsurf", "safelint-rules.md"),)`. For Claude Code it points at `(("claude", "SKILL.md"),)`. The outer tuple is a *list* of files; if a client splits its docs across multiple bundled files, list them all and the test treats the union of their text as the searchable surface. |

### 4. (Optional) Cross-agent shared file (the "secondary install")

Some clients read instructions from a *shared* file used by multiple AI tools, codex's `AGENTS.md` is the canonical example. If your client follows this pattern (the file is read by other agents too, so we can't simply overwrite it), use the **secondary-install** mechanism: safelint writes a delimited HTML-comment section into the shared file, leaving any other content the user has authored intact.

Two extra `ClientSpec` fields opt your client into this:

```python
_YOUR_SPEC = ClientSpec(
    # ... usual fields ...
    install_relpath=(".yourclient", "instructions.md"),  # primary destination, fully owned
    bundled_relpath=("yourclient", "instructions.md"),
    documentation_relpaths=(("yourclient", "instructions.md"),),
    # Cross-agent shared file:
    secondary_install_relpath=("AGENTS.md",),
    secondary_install_section_markers=(
        "<!-- safelint:begin -->",
        "<!-- safelint:end -->",
    ),
)
```

When set:

- **`install`** writes the primary destination as usual *and*, if the secondary file already exists at the scope root, edits a delimited section into it. The shared file is **never auto-created**, its existence is the user's signal that they want the cross-agent integration.
- **`update`** re-renders the section if it has drifted from the bundle.
- **`status`** escalates the overall verdict to *differs* when the section drifts (even if the primary is fresh).
- **`remove`** strips just the section. Other content in the shared file is preserved. If the file ends up empty after stripping, it is removed too.

All of this is generic, you don't write any of the lifecycle code. The install primitives in `_skill_install.py` handle every step from your two `ClientSpec` fields.

**Marker requirements:** pick markers that won't appear in your bundled instructions text or in typical user prose. The HTML-comment form (`<!-- safelint:begin -->` / `<!-- safelint:end -->`) is what codex uses; it's invisible in rendered Markdown and unlikely to collide. **Don't quote your literal markers in the bundled instructions text**, that would create a self-referential collision when the section is parsed.

### 4c. Security guards you inherit for free

The install / update / remove paths apply several guards that protect against accidental damage. You don't need to implement these in your `ClientSpec`, they apply to every client automatically:

- **Symlink refusal at the secondary destination.** If `AGENTS.md` (or whatever your secondary file is) is a symlink, `_install_secondary` / `_remove_secondary` / `_secondary_status` all refuse to follow it and print a stderr warning. This prevents an attacker (or a careless user setup) from redirecting the safelint section into an arbitrary file via a `AGENTS.md → /etc/passwd` symlink.
- **Non-regular-file refusal at the secondary destination.** If the secondary path exists but is a directory / FIFO / socket / device, the lifecycle paths refuse with a warning rather than crash on `read_text` / `write_text`.
- **`skill remove --path PATH` install-shape validation.** When the user invokes `safelint skill remove --path SOME_PATH`, the path's tail must match a registered `install_relpath`. New clients added to `_CLIENT_SPECS` extend the allow-list automatically, so your client's canonical destination is recognised the moment your spec lands.

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

Without this, the file won't be included in the wheel, `safelint skill install` would fail at `_spec_bundled_source`.

### 6. Add tests

The drift-detection tests in `tests/test_skill_install.py` are parametrised over `_CLIENT_SPECS`, so the moment your spec lands the test runner generates two new test instances for it:

* `test_skill_documents_every_active_rule[<your-name>]`, fails until your bundled docs mention every code + name in `ALL_RULES`.
* `test_skill_documents_every_supported_extension[<your-name>]`, fails until your docs mention every extension in `supported_extensions()`.

Run them targeted while iterating: `uv run pytest -k "<your-name>"`. No per-client test boilerplate to write.

For client-specific install behaviour, mirror the structure of the Cursor tests:

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

The existing Cursor tests are a good template, copy them and substitute paths / markers.

### 7. Update documentation

Three places to touch:

1. **[AI client integrations](../ai-clients/index.md)**, add a row to the *Supported clients* table.
2. **Per-client guide**, add a new page at `docs/ai-clients/clients/<client>.md` (mirroring the existing per-client pages: markers, install location, how to invoke after install, manual install) and register it under the `nav.AI client integrations.Per-client guides` entry in `mkdocs.yml`.
3. **[Manual install (`--client`)](../ai-clients/manual-install.md)**, append the `--client <name>` and `--client <name> --project` invocations.
4. **[`src/safelint/skill_files/README.md`](https://github.com/shelkesays/safelint/blob/main/src/safelint/skill_files/README.md)**, extend the supported-clients list at the top; update the install examples if the new client has a non-obvious setup.
5. **[Changelog](../project/changelog.md)**, add an entry under the next release section announcing the support.

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

1. **A file or directory the AI client *creates* automatically** when the user opts into it on a given project, these are reliable "yes this client is in use here" signals.
2. **Don't overload generic paths.** `.config/` would match too many things; `.codeium/` is specific.
3. **Multiple markers are fine.** If the client uses both a file (`.windsurfrules`) and a directory (`.codeium/`), include both, detection iterates in order and picks the first match.

The detection notice surfaces whichever marker actually fired (e.g. *"detected Windsurf (.windsurfrules)"*) so users can see which signal triggered the install.

## Choosing the install destination

Whatever location the AI client *natively* reads its skill / rules / instructions from. Examples:

| Client | Install destination |
|---|---|
| Claude Code | `~/.claude/skills/<skill_name>/` (user) or `<cwd>/.claude/skills/<skill_name>/` (project) |
| Cursor | `~/.cursor/rules/<rule>.mdc` (user) or `<cwd>/.cursor/rules/<rule>.mdc` (project) |
| Windsurf (hypothetical) | `~/.windsurfrules` (user) or `<cwd>/.windsurfrules` (project) |

The user shouldn't need to configure the client to find safelint's install, it should "just work" because the install lands where the client looks by default.

## Submission checklist

Before opening a pull request:

- [ ] New `ClientSpec` entry added to `_CLIENT_SPECS` in `src/safelint/_skill_install.py`
- [ ] Bundled artefact lives under `src/safelint/skill_files/<client>/`
- [ ] Peer-client exclusion (`_PEER_CLIENT_DIRS`) updated if applicable
- [ ] `pyproject.toml` package-data glob covers any new file extension
- [ ] Tests added: bundled-file existence, copy/symlink user/project, force replace, CLI routing, auto-detection
- [ ] Pipeline green: `pytest`, `ruff check`, `ruff format --check`, `ty check`, `safelint check src/` all clean at >=97% coverage
- [ ] Documentation updated: `docs/ai-clients/index.md` (Supported clients table), new `docs/ai-clients/clients/<client>.md` page, `docs/ai-clients/manual-install.md`, `mkdocs.yml` nav, `src/safelint/skill_files/README.md`, `CHANGELOG.md`
- [ ] PR description includes a screenshot or transcript of `safelint skill install --client <new>` succeeding on a fresh project

## Things to avoid

- **Don't add an "auto-install everything" branch that bypasses `_resolve_install_plan`.** The two-tier (cwd → home) detection is the contract; new clients plug into it via `cwd_markers` / `home_markers`, not by routing around it.
- **Don't hardcode client checks in print helpers.** All output flows through the spec, adding `if client == "windsurf"` branches inside `_print_install_success` defeats the registry pattern.
- **Don't depend on the AI client itself being installed during testing.** Tests redirect `Path.home()` / `Path.cwd()` and create fake markers; the real client doesn't need to exist on the test machine.
- **Don't break backwards compatibility for existing clients.** New entries should be additive, if you find yourself wanting to change `_CLAUDE_SPEC`, that's a separate change with its own discussion.

## See also

- [AI client integrations](../ai-clients/index.md), user-facing guide for using the AI client integrations
- [`src/safelint/_skill_install.py`](https://github.com/shelkesays/safelint/blob/main/src/safelint/_skill_install.py), the registry implementation
- [`tests/test_skill_install.py`](https://github.com/shelkesays/safelint/blob/main/tests/test_skill_install.py), the test patterns to mirror
- [Adding a new language](adding-a-language.md), adding a new language to safelint itself (a different kind of extension)
