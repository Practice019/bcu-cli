## 9. Field semantics and reliability — measured, not assumed

Section 5 lists the 28 fields. Listing a field is not the same as trusting it.
Every claim below was tested on a real 591-application scan, and each one
corrected a wrong assumption that had already been reported to a user.

### 9.1 `EstimatedSizeKb` is the installer's **self-reported** value

It comes from the registry's `EstimatedSize` value, written by the installer at
install time. It is **not** a measurement of the disk.

| Property | Measured |
|---|---|
| Populated | 500 of 591 entries (85%); **91 have no value at all (15%)** |
| Accuracy | varies wildly — see below |
| Double counting | one value per **registry entry**, so two entries naming one directory count it twice |

Measured versus reality, for the same directories:

| Application | BCU said | Actual on disk | Error |
|---|---:|---:|---|
| `Microsoft Edge` | 2109 MB | 885 MB | **2.4× too large** |
| `Microsoft Edge WebView2` | 2102 MB | 861 MB | 2.4× too large |
| `Copilot` | 2110 MB | 1164 MB | 1.8× too large |
| `Microsoft® Windows® Operating System` | **0 MB** | **9023 MB** | value absent |
| `Contoso Remote` | 243 MB | 3376 MB | **13.9× too small** |
| `Fabrikam Browser` | 1144 MB | 3348 MB | 2.9× too small |
| `Handy` | 127 MB | 907 MB | 7.1× too small |

Summing the field overestimates by about **37%** (209 GB reported vs 153 GB
measured) — but the direction of error is not uniform, so it is not a scale
factor that can be corrected arithmetically. **For any disk-space decision,
measure the directory; do not sum this field.**

### 9.2 Duplicate entries pointing at one directory

`UninstallerKind` / `DisplayName` are per registry entry, and several entries can
name the same install location. Examples from one machine:

| Directory | Entries | Effect |
|---|---:|---|
| `C:\Program Files\AcmeAnalytics` | 2 (`AcmeAnalytics`, `AcmeAnalytics 2026.01`) | 88 GB reported for 44 GB of disk |
| `C:\Program Files\Microsoft Office` | 2 (`Office`, `OneNote`) | 8.8 GB reported for 4.4 GB |
| `…\Windows Kits\10\Catalogs` | **26** | 219 MB reported across 26 SDK sub-packages |

**Deduplicate by `install_location` before totalling anything.**

### 9.3 `IsOrphaned` does **not** mean "leftover registry entry"

This is the field most easily misread, and misreading it is dangerous.

The intuitive reading — "the program is gone but the registry record remains" —
is **backwards**. Measured on a real scan:

| Check | Result |
|---|---|
| Entries BCU flags as orphaned | 75 |
| Of those, install directory **still present** | **75 of 75** |
| Of those, with a `RegistryPath` at all | **0** |
| `UninstallerKind` | `SimpleDelete` (70), `Unknown` (4), `Nsis` (1) |

`IsOrphaned` marks entries found by **directory scanning** that have no registry
record — i.e. portable or unzipped software, such as `LitwareSearch`, `NorthwindVector`,
`D:\apps\LitwareStudio`, and `C:\Program Files (x86)\dotnet`. BCU pairs them with
its own `UniversalUninstaller.exe` and a `SimpleDelete` kind, which means
**"delete that directory"**.

Consequences:

* Removing "orphaned entries" frees **zero** bytes of registry data — there is no
  registry entry to remove.
* Running BCU against that list would delete **live directories**, including .NET
  runtime and a running LitwareSearch.
* The set did not change when BCU-console was run from a different location, which
  disproves the first hypothesis (that the flag was an artefact of running from a
  throwaway directory). Always re-run the cheap experiment before reporting a
  cause.

**What "leftover registry entry" actually looks like** — a different test:

```
RegistryPath exists            # there IS a registry record
AND install_location is gone   # but the files are not
```

That condition, not `IsOrphaned`, identifies genuinely dead entries.

### 9.4 `UninstallerKind` tells you *how* it will be removed

| Kind | Meaning for a wrapper |
|---|---|
| `Msi`, `Msiexec` | `msiexec /X{ProductCode}`; reliable and silent |
| `Nsis` | `/S`; usually silent |
| `InnoSetup` | `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART` |
| `StoreApp` | needs BCU's `StoreAppHelper.exe`; not a normal uninstaller |
| `SimpleDelete` | **removes the directory outright** — check what is in it first |
| `Unknown` | inspect `UninstallString` manually |

`QuietUninstallPossible` alone is not enough to conclude silence works: 60 of 591
entries reported the flag true while carrying no quiet command. Require the flag
**and** a non-empty `QuietUninstallString`.

### 9.5 Trusted versus untrusted fields

| Reliable as-is | Requires interpretation |
|---|---|
| `DisplayName`, `DisplayVersion`, `Publisher`, `InstallDate` | `EstimatedSizeKb` (§9.1) |
| `InstallLocation`, `UninstallString` | `IsOrphaned` (§9.3) |
| `UninstallerKind`, `Is64Bit` | `QuietUninstallPossible` (§9.4) |
| `IsProtected`, `SystemComponent` | `UninstallerLocation` — points at BCU itself, not the app |

`UninstallerLocation` is worth calling out: for entries BCU cannot uninstall on
its own, it points at **BCU's own directory**, because that is where its helper
`UniversalUninstaller.exe` lives. It is not the application's location.
