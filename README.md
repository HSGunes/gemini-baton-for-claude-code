# Gemini Baton for Claude Code

**Claude conducts, Gemini codes.** A Claude Code plugin that hands implementation work to a Gemini sub-agent (via Google's `agy` / Antigravity CLI) while Claude keeps the plan, the acceptance criteria and the final verification.

Why:
- **Save your Claude usage.** The heavy lifting (writing code, iterating on failures) runs on Gemini; Claude only plans and checks.
- **Trust, but verify.** Claude runs *your* tests against Gemini's changes; the sub-agent's own report is never taken as proof.
- **Fix in context.** Failed? `devam` continues the same Gemini conversation, or `dogrula` loops test → fix automatically.
- **Safe by default.** Gemini may only write to the directories you allow; no `--dangerously-skip-permissions`.
- **Zero dependencies.** One Python 3.10+ file, standard library only, 26 tests with a fake `agy`.

```text
You ─▶ Claude Code (plan, verify)
          └─▶ baton:ajan-yonetici (Sonnet, runs the loop)   [optional]
                 └─▶ baton CLI ─▶ agy ─▶ Gemini (implements)
```

> The CLI is `baton` (legacy alias `ajan`); subcommands are Turkish for now: `baslat` start, `bekle` wait, `durum` status, `rapor` report, `devam` continue, `dogrula` verify, `iptal` cancel, `temizle` clean.

---

## 1. What It Does

In multi-agent and pair-programming workflows, a primary planner (e.g. Claude Code or a developer) designs software architectures, prepares acceptance criteria, and runs test suites, while delegating routine implementation, refactoring, or iterative fixes to a sub-agent.

`ajan` bridges this gap:
- **Direct CLI Execution:** Calls `agy` directly with `--output-format stream-json`, completely independent of IDE plugins or heavy bridge servers.
- **Process Group Isolation:** Launches background processes inside isolated process groups (`start_new_session`), handling clean termination via `SIGTERM` and forceful escalation to `SIGKILL` (after 5 seconds) if unresponsive.
- **Permission Pre-checks:** Audits `settings.json` permissions before execution, preventing failed runs due to sandbox denials.
- **State Management & Conversation Continuation:** Preserves `conversation_id` across turns, allowing multi-round feedback loops in the exact same model context.
- **Automated Verification Loops:** Provides a built-in `dogrula` command to run local unit tests and automatically feed failure outputs back to the agent for iterative correction.

---

## 2. Installation

### As a Claude Code plugin (recommended)
```bash
claude plugin marketplace add HSGunes/gemini-baton-for-claude-code
claude plugin install baton@gemini-baton
```
The plugin ships:
- `ajan` skill — the delegate → wait → verify → continue workflow,
- `baton:ajan-yonetici` subagent — runs the whole loop on a cheaper model and returns a short, evidence-backed result, keeping the main session's context small,
- `/baton:devret <task>` command — hands a task to that subagent,
- `bin/baton` launcher — the `baton` CLI (requires `python3` 3.10+ and `agy` on `PATH`).

Claude Code does not put the plugin's `bin/` on `PATH`; link it once after installing:
```bash
ln -sfn "$(ls -d ~/.claude/plugins/cache/gemini-baton/baton/* | sort -V | tail -1)/bin/baton" ~/.local/bin/baton
```
(When working from a clone, link `<clone>/bin/baton` instead so updates apply immediately.)

### Standalone CLI
```bash
python3 ajan.py --help     # no install
pip install .              # registers the `ajan` console script
```

### Development
```bash
python3 -m pytest          # uses a fake agy; never calls the real CLI
claude plugin validate --strict .
```

---

## 3. Environment Variables

| Variable | Default Value | Description |
|---|---|---|
| `AJAN_AGY` | `agy` (on `PATH`) | Path to the `agy` executable binary |
| `AJAN_DIZIN` | `$XDG_STATE_HOME/ajan` or `~/.local/state/ajan` | Root directory for storing task state and artifacts |
| `AJAN_AYAR` | `~/.gemini/antigravity-cli/settings.json` | Path to the Gemini / Antigravity permissions file |
| `AJAN_DIL` | `tr` | Output and prompt language (`tr` for Turkish, `en` for English) |

---

## 4. Permission Model

Antigravity CLI controls access via permissions defined in `settings.json`:
```json
{
  "permissions": {
    "allow": [
      "write_file(/path/to/project)",
      "command(pytest)",
      "command(git diff)"
    ]
  }
}
```

- **Write Permission:** `write_file(<absolute_path>)` covers the directory and all of its descendants recursively.
- **Command Permission:** `command(<prefix>)` matches command prefixes exactly.
- **Pre-Execution Check:** When `ajan baslat` runs, it checks whether every `--yaz` directory and `--komut` prefix is covered by `settings.json`. If permissions are missing, it halts with **exit code 2** and prints the required rules.
- **Auto-Approval:** Passing `--izin-ekle` automatically backs up `settings.json` as `settings.json.bak-<timestamp>` and adds missing rules before execution.
- **Sandbox Mode:** If no `--komut` flags are specified, `--sandbox` is enforced automatically to isolate execution.

---

## 5. stream-json & Conversation Model

`ajan` launches `agy` with `--output-format stream-json` in a background worker (`_bekci`) process:

1. **`init` Event:** Reads the session configuration and extracts `conversation_id`.
2. **`step_update` Event:** Live-tracks agent steps:
   - Tool executions (`write_file`, `edit_file`, `replace_file_content`, etc.) update `meta.json` with written files.
   - Command executions (`run_command`) update `meta.json` with executed commands.
   - Token usage metrics (`input_tokens`, `output_tokens`, `total_tokens`) are aggregated.
3. **`result` Event:** Captures final execution status, duration, and response text.
4. **Context Continuation:** When continuing a task via `devam` or during a `dogrula` cycle, `ajan` invokes `agy` with `--conversation <conversation_id>`, preserving full conversational memory.

---

## 6. Typical Orchestrator Loop

A typical orchestrator workflow (e.g. Claude Code controlling Gemini) follows this loop:

```
[Claude Code] ──► 1. Prepare Task & Launch ──► [ajan baslat ETIKET ...]
                        │
                        ▼
                  2. Await Completion       ──► [ajan bekle ETIKET] (background)
                        │
                        ▼
                  3. Inspect Summary        ──► [ajan rapor ETIKET]
                        │
                        ▼
                  4. Run Verification Tests ──► (Local test suite)
                        │
                 ┌──────┴──────┐
              Passed         Failed
                 │             │
                 ▼             ▼
              [Done]     5. Feedback & Fix   ──► [ajan devam ETIKET -m "..."]
                                                 (or automated: ajan dogrula)
```

1. **Launch (`baslat`):**
   ```bash
   ajan baslat task1 -m "Refactor parser logic" --yaz /workspace/src --komut "pytest"
   ```
2. **Wait (`bekle`):**
   ```bash
   ajan bekle task1
   ```
3. **Inspect (`rapor`):**
   ```bash
   ajan rapor task1
   ```
4. **Test:**
   The orchestrator independently runs verification tests (`pytest`, `colcon`, etc.).
5. **Continue or Validate (`devam` / `dogrula`):**
   If tests fail, provide feedback in the same context:
   ```bash
   ajan devam task1 -m "Tests failed on line 42 with KeyError. Fix root cause without relaxing tests." --bekle
   ```
   Or run the automated test-and-repair loop:
   ```bash
   ajan dogrula task1 --test "pytest tests/test_parser.py" --tur 3
   ```

---

## 7. Command Reference

### `baslat`
Starts a new background sub-agent task.
```bash
ajan baslat <tag> (-g <task_file...> | -m <prompt>) [--model <model>] [--effort <effort>] [--yaz <dir>] [--komut <prefix>] [--sure <duration>] [--sandbox] [--izin-ekle] [--bekle]
```
- Available model aliases: `flash` (`gemini-3.8-flash-high`), `flash-orta` (`gemini-3.8-flash-medium`), `argon` (`gemini-4-argon-high`), `argon-orta` (`gemini-4-argon-medium`), or any full model ID.

### `devam`
Continues an existing task with a follow-up turn in the same conversation.
```bash
ajan devam <tag> -m <followup_message> [--bekle]
```

### `dogrula`
Runs an automated test command and, if it fails, feeds the failure output back to the agent for iterative correction up to `--tur` times.
```bash
ajan dogrula <tag> --test "<command>" [--tur <max_rounds>] [--cwd <working_dir>] [--zaman-asimi <seconds>]
```

### `durum`
Displays a summary table or JSON formatted status of all tasks or a specific task.
```bash
ajan durum [<tag>] [--json]
```

### `bekle`
Blocks until specified tasks complete. Returns `0` if all finished successfully, `1` otherwise.
```bash
ajan bekle [<tag>...] [--zaman-asimi <seconds>]
```

### `rapor`
Displays structured completion report extracted from the agent's output.
```bash
ajan rapor <tag> [--ham]
```

### `izle`
Live-streams execution events in a `tail -f` fashion.
```bash
ajan izle <tag>
```

### `iptal`
Cancels a running task (sends `SIGTERM`, followed by `SIGKILL` after 5s if still alive).
```bash
ajan iptal <tag>
```

### `temizle`
Deletes completed task directories older than `--gun` days (default: 7).
```bash
ajan temizle [--gun <days>]
```

### `izin kontrol`
Audits permissions in `settings.json` without launching a task.
```bash
ajan izin kontrol [--yaz <dir>] [--komut <prefix>] [--izin-ekle]
```

---

## 8. Limitations

- **Local `agy` CLI Required:** Requires the Google Antigravity CLI binary installed and authenticated in the host environment.
- **Single Host / Process Boundaries:** Relies on local process groups (`killpg`); does not orchestrate remote worker nodes over network RPC.
- **Sandbox Limitations:** When commands are permitted, permissions must be explicitly granted in `settings.json`.

---

## 9. License

MIT — see [LICENSE](LICENSE).
