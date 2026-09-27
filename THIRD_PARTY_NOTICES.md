# Third-party notices

This project is licensed under Apache-2.0 (see [`LICENSE`](LICENSE)). It depends
on or includes the following third-party material.

## Bulk Crap Uninstaller (BCU) — the backend

- **Source:** <https://github.com/BCUninstaller/Bulk-Crap-Uninstaller>
- **Author:** Marcin Szeniak (Klocman)
- **License:** Apache-2.0
- **Relationship:** BCU is **not bundled, not modified and not recompiled** by this
  project. The wrapper locates a separately installed (or separately downloaded
  and unpacked) `BCU-console.exe` and invokes its public command-line interface:

  ```
  BCU-console list      [/Q] [/U] [/V] [/F=<Format>]
  BCU-console export    <file> [/Q] [/U] [/V] [/F=<Format>]
  BCU-console uninstall <file.bcul> [/Q] [/U] [/V] [/N] [/J=<Level>]
  ```

  Users must obtain BCU themselves. Its Apache-2.0 licence applies to BCU, not to
  this wrapper, and vice versa.

  Documentation quotations from BCU's own `help` output and from
  `doc/BCU_manual.html` are reproduced for interoperability purposes.

## HKUDS/CLI-Anything

- **Source:** <https://github.com/HKUDS/CLI-Anything>
- **License:** Apache-2.0
- **What is used:**

  1. **`src/cli_anything/bcu/utils/repl_skin.py`** — a **verbatim copy** of
     `cli-anything-plugin/repl_skin.py`. The file's own docstring instructs harness
     authors to copy it into their package. It is unmodified
     (SHA-256 `EFBBAE140830BACE95D11B3C4861D1F8A001477C18B7BC68F519066EB9C01B11`)
     and provides the terminal skin used by the interactive REPL; it depends on
     `prompt-toolkit`.

  2. **Project layout** — the `cli_anything/<software>/` + `core/` + `utils/` +
     `tests/` structure follows the CLI-Anything convention described in
     `cli-anything-plugin/HARNESS.md`.

If you redistribute this project, keep this notice together with the Apache-2.0
`LICENSE`, as that licence requires.

## Runtime dependencies

Installed automatically by pip:

| Package | License | Purpose |
|---|---|---|
| [`click`](https://github.com/pallets/click) | BSD-3-Clause | CLI framework |
| [`prompt-toolkit`](https://github.com/prompt-toolkit/python-prompt-toolkit) | BSD-3-Clause | REPL input (via `repl_skin.py`) |
| `wcwidth` | MIT | transitive dependency of prompt-toolkit |

Development only:

| Package | License |
|---|---|
| [`pytest`](https://github.com/pytest-dev/pytest) | MIT |
| `pytest-cov` | MIT |

Standard-library modules used (`ctypes`, `json`, `subprocess`, `winreg`, `xml`,
`zipfile`, …) are covered by the Python Software Foundation License.

## Test fixtures

`src/cli_anything/bcu/tests/fixtures/` contains output captured from a real
`BCU-console.exe` run on the author's machine: `list_591_apps.json`,
`list_plain_utf16.txt`, `dryrun_1match_stderr.txt`, `valid_list.bcul`.

These contain **application names and install paths** from that machine. They are
kept because the parser must be tested against real output rather than invented
samples. No credentials, licence keys or personal files are included; if you fork
this project, consider regenerating them on your own machine.
