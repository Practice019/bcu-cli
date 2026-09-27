---
name: "cli-anything-bcu"
description: "Uninstall and audit Windows applications from the command line via Bulk Crap Uninstaller: list everything installed, find orphaned registry entries, inspect uninstall commands, and remove programs by name with a dry-run-first safety protocol. Use for uninstalling software, cleaning up broken/orphaned installs, inventorying installed applications, or answering 'what is installed and how big is it' on Windows."
---

# cli-anything-bcu

Agent-native CLI for **inventing and removing** Windows applications, powered by
[Bulk Crap Uninstaller](https://github.com/BCUninstaller/Bulk-Crap-Uninstaller).

## When to use this skill

- "Uninstall <program>" on Windows
- "What is installed on this machine and how big is it?"
- "Are there orphaned registry entries from deleted apps?"
- "Which of these can be uninstalled silently?"
- "Clean up leftover files after uninstalling something"

## Prerequisites

- Windows, Python 3.10+
- `BCU-console.exe` — instal BCU (`winget install Klocman.BulkCrapUninstaller`) or
  unzip the official release, which contains `BCU-console.exe`
- .NET 8 desktop runtime

Check first, always:

```bash
bcu-cli info --json
```

```json
{"found": true, "console": "…\\BCU-console.exe", "source": "PATH",
 "is_admin": false, "index_exists": true}
```

`is_admin: false` is fine for `query`, but **`scan`/`uninstall` will fail** —
BCU-console declares `requireAdministrator` and the wrapper refuses rather than
failing obscurely.

## The two-phase workflow (do not skip phase 1)

```bash
# PHASE 1 — in an elevated shell, once (~60 s: it is a full-system scan)
bcu-cli scan --json

# PHASE 2 — anywhere, instant, no admin
bcu-cli query summary
bcu-cli query list --top 20
bcu-cli query orphaned
bcu-cli query show "Google Chrome"
```

**Never query by re-scanning.** `list` takes ~58 seconds; the index exists so that
questions cost milliseconds.

## Uninstalling: dry run first, always

```bash
# 1. DRY RUN — changes nothing, shows what BCU would do
bcu-cli uninstall "OldApp"

# 2. read the output, then act (both flags required)
bcu-cli uninstall "OldApp" --apply --confirm

# with silent uninstaller and leftover cleanup
bcu-cli uninstall "OldApp" --apply --confirm --quiet --junk VeryGood
```

`--apply` without `--confirm` is **refused by design**. `--unattended` (BCU's `/U`,
which suppresses prompts) additionally requires both — BCU's own help warns that
`/U` should only be used after thorough testing.

## Guidance for agents

1. **Always pass `--json`.** Failures are `{"error": ..., "type": ...}` with a
   non-zero exit code, so stdout is never empty.
2. **Check the exit code.** `0` success, `1` handled failure (not found / not
   elevated / refused / bad input), `2` usage error.
3. **A dry run that matches nothing exits 1** — that is BCU's documented
   behaviour, not a crash. It means your pattern matched no installed app.
4. **Run the dry run before applying, every time.** It is cheap (~30 s) and it
   catches a wrong-name match before damage is done.
5. **Ambiguity is refused, not guessed.** If several apps match, you get a list
   and a suggestion; pick a narrower name or pass `--first`.
6. **Protected components are refused.** Windows system entries cannot be removed
   through this tool.
7. **Home the elevation boundary.** Elevate a shell and run the CLI there; the
   wrapper will not self-elevate, and `scan`/`uninstall` fail without it.

## Command reference

| Command | Admin? | Purpose |
|---|---|---|
| `info` | no | Console location, version, elevation, index status |
| `scan` | **yes** | Full scan → local index (~60 s) |
| `query summary` | no | Index overview |
| `query list -n 20 [--orphaned] [--quiet-capable]` | no | List apps |
| `query show "<name>"` | no | Full detail for one app |
| `query orphaned` | no | Registry entries whose files are gone |
| `query top -n 30` | no | Largest apps by BCU's estimate |
| `uninstall "<name>"` | **yes** | Dry run (add `--apply --confirm` to act) |
| `report -o apps.csv` | no | csv / json / markdown / html / table |
| `export -o apps.json` | **yes** | BCU's own export |
| `list-file "<name>" -o x.bcul` | no | Generate a BCU list, run nothing |

Global flags `--json`, `--console`, `--index-file` work before or after the verb.

## Examples

```bash
# disk-usage triage before uninstalling
bcu-cli --json query list --top 30
bcu-cli query show "Adobe Creative Cloud"

# broken installs: files gone, registry record remains
bcu-cli --json query orphaned
bcu-cli uninstall "Ghost App" --apply --confirm

# which of these will show an installer wizard?
bcu-cli query list --quiet-capable

# something you can only match loosely
bcu-cli query list --top 200 | grep -i chrome
bcu-cli uninstall "Google Chrome" --first   # dry run anyway
```

## Failure modes and what to do

| Symptom | Cause | Fix |
|---|---|---|
| `BCU-console.exe not found` | BCU not installed / not unpacked | `winget install Klocman.BulkCrapUninstaller`, or set `BCU_CONSOLE`, or `--console` |
| `needs an elevated shell` | BCU-console declares `requireAdministrator` | run from an elevated terminal |
| `no scan index at …` | `query` before `scan` | run `bcu-cli scan` (elevated) |
| `N applications match 'x'` | ambiguous pattern | use a fuller name, or `--first` |
| dry run exits 1, matched 0 | pattern matched nothing | check `query list` for the exact name |
| `BCU-console timed out` | very slow machine, or the scan is huge | raise `--timeout` |
| `refusing to uninstall protected system component(s)` | it is a Windows component | leave it alone |

## What this skill does not do

- **No `--json` detail from BCU's `uninstall`** — BCU ignores `/F=json` on that
  command and reports on stderr; the wrapper parses that stderr instead, so a
  dry run's result is a text summary, not a rich object.
- **No batch uninstall by list file from the CLI.** Generate the `.bcul` with
  `list-file`, then hand it to BCU directly if you need BCU's full batch engine.
- **No junk-cleanup preview details.** `--junk <level>` is passed through and
  validated, but the list of items BCU would delete is not parsed.
- **No non-Windows support** — BCU is a Windows program.
