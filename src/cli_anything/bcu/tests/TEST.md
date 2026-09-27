# TEST.md — cli-anything-bcu

Software: **Bulk Crap Uninstaller (BCU) v6.3.0** — Apache-2.0, Marcin Szeniak (Klocman)
Wrapper: `bcu-cli` (standalone repo)
Reconnaissance: [`docs/BCU.md`](../../../../docs/BCU.md)

> Part 1 = the test plan, written **before** the code.
> Part 2 = the real results, appended after running.

---

## Part 0 — What reconnaissance already proved (measured, not assumed)

These four facts decide the whole design, and each one gets a regression test:

| # | Fact | Evidence | Design consequence |
|---|---|---|---|
| **B1** | `BCU-console.exe` **ships in the official release** | extracted `BCUninstaller_6.3.0_net8.0-windows10.0.18362.0.zip` → `BCU-console.exe` 302,592 B | no compilation needed; CLI locates or downloads it |
| **B2** | It **requires administrator** | launch failed with `请求的操作需要提升`; manifest has `<requestedExecutionLevel level="requireAdministrator">` | split slow-admin-scan from fast-no-admin-query |
| **B3** | `list` is a **58-second full-system scan** producing **591 apps / 746 KB JSON / 28 fields** | timed run: `exit=0 elapsed=57.9s` | must index once, not scan per query |
| **B4** | `uninstall` takes **only a `.bcul` file** and reports on **stderr**, `/F=json` notwithstanding | `uninstall probe.bcul /N /F=json` → `stdout=0 B stderr=799 B` | wrapper must generate `.bcul` and parse stderr |

Two more that shape safety:

| # | Fact | Evidence |
|---|---|---|
| **B5** | `/N` is a real dry-run | `Dry run finished. No changes were made.` |
| **B6** | Exit codes: `0` ok, `1` bad args **or dry-run matched nothing**, `1223` cancelled | source `ShowHelp` + measured `exit=1` on a no-match dry-run |

---

## 1.1 Unit tests `tests/test_core.py` (synthetic + real fixtures, **no BCU needed**)

Synthetic fixtures live in `tests/fixtures/` (regenerated — the original capture leaked a real application inventory, so it was replaced with generated data of the same shape):
`list_591_apps.json` (746 KB), `dryrun_1match_stderr.txt`, `dryrun_nomatch_stderr.txt`,
`list_plain_utf16.txt`, `valid_list.bcul`.

| Module | Function | Coverage | Est. |
|---|---|---|---|
| `core/model.py` | `Application.from_bcu_json` | all 28 fields; nulls; `EstimatedSizeKb` Int64; booleans; missing key tolerance | 8 |
| `core/model.py` | `Application` properties | `is_uninstallable`, `is_quiet_capable`, `size_human`, `kind_normalized` | 6 |
| `core/parse.py` | `parse_list_json` | real 591-app fixture; empty array; malformed JSON; top-level type mismatch | 6 |
| `core/parse.py` | `parse_dry_run_stderr` | **B4**: the real 1-match stderr; no-match stderr; "Found N applications"; "matched by the list"; counts line | 8 |
| `core/parse.py` | `decode_console_output` | **UTF-16LE vs UTF-8** (**B3**-adjacent); BOM; CJK app names | 6 |
| `core/listfile.py` | `build_bcul` | **B4/B3**: XML shape; escaping `&<>"`; CJK names; exclude filters; round-trip parse | 10 |
| `core/index.py` | `Index` | save/load round-trip; atomic write; corrupt file; schema version; counts | 8 |
| `core/select.py` | `select_apps` | exact / substring / case-insensitive match; ambiguity detection; zero-match; glob; by registry key | 10 |
| `core/plan.py` | `build_plan` | **B6**: dry-run before real; refuses `/U` without explicit opt-in; refuses `IsProtected`; reports quiet vs loud | 9 |
| `utils/bcu_backend.py` | `find_console` | env var override; explicit path; missing → actionable error | 5 |
| `utils/bcu_backend.py` | `build_args` | `list/export/uninstall` argv; `/F=json`; `/N`; `/Q`; `/J=<level>` validation | 9 |
| `utils/bcu_backend.py` | `admin detection` | reports elevation state; does not attempt self-elevation | 3 |
| `core/report.py` | `render` | csv / json / table / markdown; column subset; top-N | 7 |

≈ **95 unit tests**.

## 1.2 E2E tests `tests/test_full_e2e.py` (**real BCU-console, admin, no degradation**)

- **Real `list /F=json`**: assert > 100 apps, every field of the first entry maps, JSON parses, elapsed recorded.
- **Real `list` plain**: assert the UTF-16LE decode path produces readable text with a header row.
- **Real dry-run, 1 match**: build `.bcul` for a known-installed app → `/N` → parse stderr → assert exactly 1 matched and the name matches; assert **exit 0**.
- **Real dry-run, 0 matches**: same but a nonsense name → assert **exit 1** (**B6**).
- **Safety: a dry-run must not change the system** — hash the target app's registry key and install dir before/after, assert identical.
- **Real `export`**: writes xml/json, both parse, entry count matches `list`.
- **Index workflow**: scan → save → reload → `query` returns the same app count without invoking BCU (assert by timing and by not passing an exe).
- **`TestCLISubprocess`**: `--help`, `scan --json`, `query list --json`, `info --json`, `uninstall --dry-run --json`, and a failing path; uses `_resolve_cli("cli-anything-bcu")`, no `cwd`, `CLI_ANYTHING_FORCE_INSTALLED` supported.

## 1.3 Explicitly out of scope

- **Actually performing an uninstall.** The E2E suite must never remove a real application:
  destructive, environment-specific, and not reproducible in CI. The wrapper's own logic
  (`/N` first, explicit opt-in for `/U`) is unit-tested; the real uninstall path is
  exercised **manually once, on a throwaway app**, and recorded here.
- **BCU-console's own junk-cleanup levels** beyond validating the `/J=` argument.
- **Non-Windows.** BCU is a Windows program.

---

## Part 2 — Test results

### 2.1 Summary

| Suite | Command | Result | Needs admin | Needs BCU |
|---|---|---|---|---|
| Unit + CLI bindings | `pytest test_core.py test_cli_bindings.py` | **149 passed in 0.77s** | no | no |
| End-to-end | `pytest test_full_e2e.py` (elevated) | **22 passed, 1 skipped, 0 failed** (164.89s) | **yes** | **yes** |

The unit suite runs in **under a second** and needs neither administrator rights
nor BCU installed — that is what makes it usable as a CI gate.

The E2E suite needs both. First full run: **22 tests in 166.65 s**, 20 passing.

`validate_self.py` reports **68/68** structural and convention checks.

### 2.2 Unit suite — by test class

| Test class | Tests | What it covers |
|---|---:|---|
| `TestApplicationModel` | 12 | all 28 BCU fields, nulls, Int64 sizes, `flag AND command` rule, round-trip |
| `TestParseListJson` | 6 | real 591-app fixture, empty, malformed, wrong root type |
| `TestDecodeConsoleOutput` | 7 | UTF-16LE vs UTF-8, BOM, CJK, NUL-density detection |
| `TestParseDryRunStderr` | 8 | real 1-match and no-match stderr, counts, dry-run marker |
| `TestBuildBcul` | 15 | XML shape vs the proven-good fixture, escaping, CJK, methods |
| `TestIndex` | 8 | atomic save, reload, corrupt/wrong-schema rejection |
| `TestSelectApps` | 14 | exact/glob/registry-key match, ambiguity, protected exclusion |
| `TestPlan` | 14 | dry-run default, refusal rules, `/U` gating, junk levels |
| `TestReport` | 9 | csv/json/table/markdown, columns, top-N |
| `TestFindConsole` / `TestBuildArgs` / `TestAdmin` | 21 | discovery, argv builders, elevation reporting |
| `TestHelpRunsForEveryCommand` | 15 | `--help` binds all 13 command paths |
| `TestNoCallbackBindingErrors` / `TestKnownGoodBindings` | 12 | the `--apply` regression |

### 2.3 Unit suite output (verbatim)

```text
147 passed in 0.70s
```

### 2.4 E2E output — first real elevated run (verbatim)

```text
TestRealBackend::test_console_exists_and_is_named_right PASSED
TestRealBackend::test_help_exits_zero PASSED
TestRealBackend::test_version_is_parseable_from_the_banner PASSED
TestRealBackend::test_list_json_parses_and_covers_the_machine PASSED
TestRealBackend::test_every_field_of_a_real_entry_maps PASSED
TestRealBackend::test_scan_is_a_full_system_pass_not_an_empty_one PASSED
TestRealBackend::test_plain_list_decodes_as_utf16 PASSED
TestRealBackend::test_dry_run_matches_exactly_one_app PASSED
TestRealBackend::test_dry_run_with_no_match_exits_one PASSED
TestRealBackend::test_dry_run_does_not_touch_the_system PASSED
TestRealBackend::test_export_produces_a_parseable_file PASSED
TestIndexWorkflow::test_scan_save_reload_matches PASSED
TestIndexWorkflow::test_query_does_not_invoke_bcu PASSED
TestIndexWorkflow::test_report_round_trips_from_the_real_index PASSED
TestCLISubprocess::test_help_lists_the_command_groups PASSED
TestCLISubprocess::test_version PASSED
TestCLISubprocess::test_info_reports_discovery_and_elevation PASSED
TestCLISubprocess::test_global_flag_after_subcommand PASSED
TestCLISubprocess::test_query_without_index_fails_with_a_useful_message PASSED
TestCLISubprocess::test_list_file_generates_bcul_without_running_anything PASSED
TestCLISubprocess::test_uninstall_without_index_fails_cleanly FAILED
TestCLISubprocess::test_uninstall_refuses_apply_without_confirm FAILED
================== 2 failed, 20 passed in 166.65s (0:02:46) ===================
```

### 2.5 What the E2E suite proves, and the bug it caught

Against the **real** binary, so every Part 0 claim is re-verified:

- **B1** the discovered file is `BCU-console.exe` and `help` exits 0
- **B2** the version is read from BCU's own banner, not hardcoded
- **B3** a real scan yields a substantial app set, every field maps, and the plain
  (non-`/F`) output decodes as UTF-16 rather than mojibake
- **B4** a generated `.bcul` is accepted, matches exactly one app, and the result
  is read from **stderr** because `/F=json` is ignored on `uninstall`
- **B6** a no-match dry run exits **1**, exactly as BCU documents
- **safety** `test_dry_run_does_not_touch_the_system` fingerprints the target's
  install directory before and after a dry run and requires identical results

**The 2 failures were one real bug, and only E2E could find it:**

```text
uninstall_cmd() got an unexpected keyword argument 'apply'. Did you mean 'apply_'
```

`@click.option("--apply")` derives the parameter name `apply`, but the callback
took `apply_` (`apply` is a Python builtin). **Every** `uninstall --apply`
invocation was therefore dead on arrival.

No unit test could have caught it. The option decorators are wrapped by
`with_globals` / `handle_error`, so the callback signature is `(*args, **kwargs)`
and static inspection sees nothing wrong — an AST audit produced only false
positives. The only reliable detector is to *actually invoke every command*.

Fixes:

1. bind explicitly — `@click.option("--apply", "apply_", ...)`
2. **`test_cli_bindings.py`**, a permanent regression suite: `--help` on all 13
   command paths, plus invoking each command with no arguments, asserting Click
   never reports a binding error.

Verification of the fix without elevation (the binding error occurs at parse time,
before the privilege check):

```text
ok   uninstall SomeApp --apply
ok   uninstall SomeApp --apply --confirm
ok   uninstall SomeApp --apply --confirm --unattended
ok   uninstall SomeApp
ok   uninstall SomeApp --quiet --junk VeryGood
```

### 2.6 Defects found and fixed during development

| # | Defect | Found by | Fix |
|---|---|---|---|
| 1 | `to_dict()` was not re-readable: it emits snake_case names but the parser only accepted BCU's `DisplayName`. `Index.load()` would silently lose every `DisplayName`. | unit test `test_to_dict_is_round_trippable` | accept **both** spellings; keep snake_case out of `extra` |
| 2 | UTF-16 detection failed for CJK output: the tell was "byte 1 is NUL", true for BCU's ASCII banner but not when the first char is CJK (`闲` = 0x95F2). | unit test `test_cjk_survives_utf16` | detect by **NUL density** over the first 512 bytes |
| 3 | `--apply` was unusable (see §2.5). | **E2E only** | explicit parameter binding + binding regression suite |
| 4 | A pure-CJK UTF-16 stream with no ASCII prefix is genuinely ambiguous. | reflection on #2 | documented as a limitation, with an explicit test |
| 5 | **`--apply` without `--confirm` ran a real uninstall.** The guard only fired for `/U`, so the documented contract was not enforced. A test attempting exactly that combination performed a genuine uninstall attempt. | **E2E** — and only because the test *did* the dangerous thing rather than mocking it | the guard now fires for **every** apply run; a refused plan carries an empty `argv`, so BCU cannot be invoked at all |



**Defect 5 deserves its own note, because two separate failures let it through:**

1. **The unit test that appeared to cover it did not.**
   `test_apply_mode_without_confirm_is_refused` passed `unattended=True`, exercising
   a *different* branch; nothing tested the bare `uninstall X --apply` case. Its
   sibling `test_apply_mode_requires_explicit_mode` went further and asserted the
   dangerous behaviour was *correct*.
2. **The E2E assertion was too lenient.** It accepted "any non-zero exit", so when
   BCU returned 13 the result looked pass-shaped. It now asserts three things: the
   run is refused, the message names `--confirm`, and `argv` is empty so BCU was
   never invoked. A positive control (`--apply --confirm` must get past the gate)
   guards against the refusal becoming a wall.

**Impact on this machine: none.** BCU exited 13 (an unexpected error) without
removing anything; `C:\Program Files\AcmeArchiver` and its registry entry were verified intact
afterwards. The bug was real regardless — intending to remove AcmeArchiver without an
explicit confirmation is wrong whether or not BCU happened to fail.

Verification of the fix, without needing elevation:

```text
scenario A: --apply            refused=True  will_run=False  argv=[]
scenario B: --apply --confirm  refused=False argv=['uninstall', 'x.bcul']  destructive=True
```

Three of my own test expectations were also wrong and were corrected rather than
worked around: XML element text does not need `"` escaped (only attributes do);
a realistic fixture must set `uninstall_possible=True` for the planner to accept
it; and the command-path list must exclude the root command's own name.

### 2.7 Coverage gaps, stated plainly

- **A real uninstall is never executed by the suite.** Destructive,
  environment-specific, unreproducible in CI. What *is* covered: the dry-run path
  end to end against the real binary, plus every refusal rule in unit tests
  (ambiguity, protected components, missing `--confirm`, no elevation, empty
  match). **Manual verification on this machine**: the dry run reported
  `1 application(s) were matched by the list` and `Dry run finished. No changes
  were made.` — *apply* was deliberately not run.
- **`/J=` junk-cleanup content is not parsed.** The level is validated and passed
  through; the items BCU would delete are not surfaced.
- **Batch uninstall by a pre-made list is not exposed.** `list-file` generates the
  `.bcul` for BCU's own engine.
- **Non-Windows is untestable** — BCU is a Windows program. Only the unit suite is
  cross-platform, because it never invokes BCU.
- **BCU version drift.** The suite pins behaviours of 6.3.0. A release that changes
  the `list` JSON shape or the stderr wording would trip
  `test_list_json_parses_and_covers_the_machine` or
  `test_dry_run_matches_exactly_one_app` rather than being silently absorbed.
