# Security Policy

## Supported Versions

Only the latest release is supported with security updates.

## Reporting a Vulnerability

Please report security vulnerabilities privately via GitHub Private Vulnerability Reporting:

1. Open the repository's **Security** tab.
2. Select **Report a vulnerability** (or go directly to [New Security Advisory](https://github.com/HSGunes/gemini-baton-for-claude-code/security/advisories/new)).

Please do **not** open a public GitHub issue for security reports.

## Permission Model Summary

Gemini Baton validates `agy`'s allow-list (`settings.json`, overridable via `AJAN_AYAR`) before launching a task:

- **Scoped write access (`--yaz` / `--write`):** Gemini may only write to directories passed via `--yaz`, which must be covered by `write_file(<path>)` allow rules in `settings.json`.
- **Sandboxed by default (`--komut` / `--sandbox`):** When no `--komut` (`--allow-cmd`) prefixes are provided (or when `--sandbox` is set), `baton` launches `agy` with `--sandbox`, keeping terminal execution disabled. Permitted command prefixes require exact `command(<prefix>)` rules in `settings.json`.
- **Fail-closed preflight (exit code `2`):** If any required write or command rule is missing, `baton` prints the missing rules and exits with code `2` before starting `agy`.
- **Opt-in permission updates (`--izin-ekle` / `--add-perms`):** `baton` never grants permissions on its own. Missing rules are written to `settings.json` only when explicitly requested with `--izin-ekle`, after validating the existing JSON and saving a timestamped backup (`settings.json.bak-<timestamp>`).
