# bcu-cli

**Agent-native CLI for Windows application uninstalling, powered by [Bulk Crap Uninstaller](https://github.com/BCUninstaller/Bulk-Crap-Uninstaller).**

BCU is the best open-source uninstaller on Windows. `BCU-console.exe` is its
command-line half — powerful, but awkward to drive: it needs administrator rights
for *everything*, its `list` is a ~58-second full-system scan, and `uninstall`
accepts only a generated `.bcul` list file while reporting results on **stderr**.
This wrapper turns that into something a human or an agent can actually use:

```
scan  (admin, ~60 s, once)  ->  local index  ->  query (no admin, instant)
uninstall (admin):            dry-run first, apply only when explicitly confirmed
```

## Why this is a real wrapper, not a shim

Five behaviours were measured against BCU-console 6.3.0 (see
[`docs/BCU.md`](docs/BCU.md)); each one gets a regression test:

| Measured behaviour | What it means here |
|---|---|
| `BCU-console.exe` **ships inside the official release zip** | no compilation needed; discovery covers installed *and* unpacked copies |
| It declares **`requireAdministrator`** | scans/uninstalls need an elevated shell; the wrapper refuses with a usable message instead of failing obscurely |
| `list` is a **58-second full-system scan** | index once, then query instantly without admin |
| `uninstall` takes **only a `.bcul` file**, and reports on **stderr** | the wrapper generates the list and parses stderr |
| `/N` is a documented **dry-run** | the default is always the non-destructive path |

Plus two safety rules the wrapper enforces itself:

- **`--apply` alone is not enough.** An irreversible run requires **`--apply --confirm`**.
- **`/U` (unattended) is never implied.** BCU's own help screams about it; so do we.

## Requirements

- **Windows 10/11** (BCU is a Windows program)
- **Python 3.10+**
- **BCU-console.exe** — from any of:
  - the official release: unzip `BCUninstaller_*_net8.0-windows*.zip`, which contains `BCU-console.exe`
  - `winget install Klocman.BulkCrapUninstaller`
  - or point `BCU_CONSOLE` / `--console` at it
- **.NET 8 desktop runtime** (BCU requires `Microsoft.NETCore.App 8` + `Microsoft.WindowsDesktop.App 8`)
- An **elevated terminal** for `scan` / `export` / `uninstall`

## Install

```bash
git clone https://github.com/Practice019/bcu-cli
cd bcu-cli
pip install .
cli-anything-bcu info --json
```

For development, `pip install -e .`.

## Usage

```bash
# 1. What is on this machine and can I even run it?
bcu-cli info --json
bcu-cli info                       # says "elevated: NO — scans will fail" when not admin

# 2. Scan once, from an ADMIN terminal (~60 s)
bcu-cli scan --json

# 3. Ask questions all day — fast, no admin, no re-scan
bcu-cli query summary
bcu-cli query list --top 20
bcu-cli query list --orphaned
bcu-cli query show "Google Chrome"
bcu-cli query top -n 30
bcu-cli report -o apps.csv
```

### Uninstalling

```bash
# DRY RUN — shows exactly what would happen, changes nothing
bcu-cli uninstall "AcmeArchiver"

# only after reading the dry run
bcu-cli uninstall "AcmeArchiver" --apply --confirm

# prefer a silent uninstaller, and also clean leftovers
bcu-cli uninstall "AcmeArchiver" --apply --confirm --quiet --junk VeryGood
```

`--apply` without `--confirm` is refused on purpose. `--unattended` (BCU's `/U`)
additionally requires both, because it suppresses BCU's own prompts.

### Generating a list without running anything

```bash
bcu-cli list-file "Google Chrome" "Firefox" -o browsers.bcul
# then hand it to BCU yourself, or inspect it
```

Useful when you want BCU's own GUI to review the list first.

## Command reference

| Command | Admin? | Purpose |
|---|---|---|
| `info` | no | Locate BCU-console, version, elevation state, index status |
| `scan` | **yes** | Full scan → local index (~60 s) |
| `query summary` | no | Index overview |
| `query list` | no | List applications (sort, filter, formats) |
| `query show <name>` | no | Detail for one application |
| `query orphaned` | no | Registry entries whose files are gone |
| `query top` | no | Largest applications by BCU's size estimate |
| `uninstall <name>` | **yes** | Dry-run by default; `--apply --confirm` to act |
| `report -o <file>` | no | Write csv/json/markdown/html/table |
| `export -o <file>` | **yes** | BCU's own export |
| `list-file <names...> -o <file>` | no | Generate a `.bcul`, run nothing |

Global options (`--json`, `--console`, `--index-file`) work **before or after** the
verb: `--json info` and `info --json` are equivalent.

## Safety model

Uninstalling is irreversible, so the wrapper never guesses:

| Situation | Behaviour |
|---|---|
| Several applications match | **refuses**, lists them, suggests a narrower pattern (or `--first`) |
| The match is a protected system component | **refuses** |
| No application matches | **refuses**, with the reason |
| The app has no uninstall command | **refuses** (BCU reports *<name>* as not uninstallable) |
| `--apply` without `--confirm` | **refuses** |
| `--unattended` without `--confirm` | **refuses** |
| Not elevated | **refuses**, telling you to use an elevated shell (never self-elevates) |

A dry run additionally proves itself: the E2E suite fingerprints the target's
install directory before and after, and fails if anything changed.

## JSON output and exit codes

Every command accepts `--json` and prints one JSON document; failures print
`{"error": ..., "type": ...}` with a non-zero exit code, so `--json` never yields
empty stdout.

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | A handled failure (not found, not elevated, refused, bad input) |
| `2` | A usage error (unknown option, missing argument) |

BCU's own exit codes are surfaced where they matter: a dry run that matches
nothing exits **1** (BCU's documented behaviour).

## Architecture

```
src/cli_anything/bcu/
  bcu_cli.py            Click CLI: info / scan / query / uninstall / report / export / repl
  core/
    model.py            the 28 BCU fields, and the "flag AND command" rule
    parse.py            JSON list, UTF-16 console output, stderr dry-run report
    listfile.py         .bcul generation (XmlSerializer-compatible XML)
    index.py            atomic local index of a scan
    select.py           pattern → application set, ambiguity-aware
    plan.py             dry-run/apply decisions and refusals
    report.py           table / csv / json / markdown / html
  utils/
    bcu_backend.py      discovery, elevation check, argv builders, execution
    repl_skin.py        terminal skin (see THIRD_PARTY_NOTICES.md)
```

Design rule: only `utils/bcu_backend.py` and `core/model.py` know BCU's spellings,
so a BCU upgrade is a one-file change per concern.

## Testing

```bash
# 130+ tests, ~1 second, no admin, no BCU needed, any OS
python -m pytest src/cli_anything/bcu/tests/test_core.py src/cli_anything/bcu/tests/test_cli_bindings.py

# 22 E2E tests: real BCU-console, real scans, MUST be run elevated
python -m pytest src/cli_anything/bcu/tests/test_full_e2e.py
```

`test_cli_bindings.py` exists because of a real bug: `--apply` bound to a
parameter named `apply` while the function took `apply_`, which no unit test could
see (the option decorators are wrapped, so the callback signature is `*args,
**kwargs`). Only invoking every command catches that class of error.

**The suite never performs a real uninstall.** That is destructive,
environment-specific and unreproducible in CI; the dry-run path is exercised for
real and the safety refusals are unit-tested. See TEST.md §1.3.

## Documentation

- [`docs/BCU.md`](docs/BCU.md) — measured reconnaissance: exact switches, timings,
  the JSON schema of all 28 fields, and the three traps
- [`src/cli_anything/bcu/tests/TEST.md`](src/cli_anything/bcu/tests/TEST.md) — test plan and results

## License

Apache-2.0 — see [`LICENSE`](LICENSE).

BCU itself is Apache-2.0 by Marcin Szeniak (Klocman). It is **not** bundled here;
you install it separately. This project only drives its public command-line
interface. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
