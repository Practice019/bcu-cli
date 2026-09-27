# BCU-console — 实测事实（Phase 1 侦察结论）

> **本文所有结论都来自真机实测，不是文档推断。** 每条都附证据。
> 侦察脚本与原始产物：`D:\project_GIT\_bcu_probe\`

被包装的程序：**Bulk Crap Uninstaller (BCU) v6.3.0**，Apache-2.0，作者 Marcin Szeniak (Klocman)。

---

## 1. 决定性前提：官方 release 确实带 `BCU-console.exe`

下载 `BCUninstaller_6.3.0_net8.0-windows10.0.18362.0.zip`（11.8 MB）解包验证：

```
BCU-console.exe          302,592 B   ← 官方随包发布
BCU-console.dll          332,800 B
BCU-console.deps.json     12,669 B
BCU-console.runtimeconfig.json 515 B
BCUninstaller.exe        302,592 B   ← 同尺寸：同一宿主，不同入口
+ UninstallTools.dll / KlocTools.dll / es.exe / StoreAppHelper.exe …
共 252 个条目
```

**含义**：用户不需要自行编译。`pip install` 之后由 CLI 负责定位/下载/解包。

依赖框架：`Microsoft.NETCore.App 8.0` + `Microsoft.WindowsDesktop.App 8.0`
（本机已装 8.0.31 / 9.0.20 / 10.0.12，实测可运行）

---

## 2. 强制管理员权限（实测）

首次以普通用户启动直接失败：

```
An error occurred trying to start process 'BCU-console.exe' … 请求的操作需要提升。
```

从 `BCU-console.exe` 嵌入 manifest 中提取到：

```xml
<requestedExecutionLevel level="requireAdministrator" uiAccess="false" />
```

**含义**：`list` / `export` / `uninstall` **全部**需要提权，每次调用都会弹 UAC。
架构必须把「需要管理员的慢扫描」与「无需管理员的快速查询」分开。

---

## 3. 命令与开关（源码 + 实跑双重确认）

```
BCU-console help | /?                                   显示帮助
BCU-console list    [/Q] [/U] [/V] [/F=<Format>]         列出已安装程序
BCU-console export  <file> [/Q] [/U] [/V] [/F=<Format>]  导出到文件
BCU-console uninstall <file.bcul> [/Q] [/U] [/V] [/N] [/J=<Level>]  卸载
```

| 开关 | 含义 |
|---|---|
| `/Q` | 尽可能使用静默卸载器（默认只用「明面」的） |
| `/U` | 无人值守（**不询问确认**） |
| `/V` | 详细日志 |
| **`/N`** | **干跑预览**，`--dry-run` 亦可。不卸载、不删任何东西 |
| `/J=<Level>` | 卸载后清残留，级别 `VeryGood`(默认) / `Good` / `Questionable` / `Bad` / `Unknown` |
| `/F=json\|xml` | 输出格式，`--format=` 亦可 |

退出码：`0` 成功 · `1` 参数错误或干跑无匹配 · `1223` 用户取消 · `13` 意外异常

> ⚠️ **纠正一条网上流传的过时信息**：GitHub issue #947 请求增加 `--dry-run`，
> 但 `/N` 在 6.3.0 中**已经实现**。以源码与实跑为准，不要以 issue 快照为准。

---

## 4. 实测耗时与数据规模

| 操作 | 耗时 | 输出 |
|---|---|---|
| `list /F=json` | **57.9 s** | 746,405 B，**591 个应用** |
| `list`（无 /F） | 26.4 s | 126,548 B，**UTF-16LE**（首字节 `42 00 43 00` = "BC"） |
| `uninstall <bcul> /N` | 29.0 s | 结果走 **stderr**（见 §6） |
| `uninstall <bcul> /N`（无匹配） | — | 退出码 **1** |

**含义**：
1. `list` 是全系统扫描（注册表 32/64 + 商店 + Steam + 逐个查版本），**慢是正常的**
2. 必须「扫描一次 → 本地索引 → 多次查询」，否则每次查询 58 秒
3. 天然输出分两种编码，JSON 时才是 UTF-8

---

## 5. JSON 结构（591 条真实样本统计）

**顶层是数组**（不是对象），每应用 **28 个字段**：

| 字段 | 非空/591 | 类型 | 说明 |
|---|---|---|---|
| `DisplayName` | 591 | String | 显示名 |
| `DisplayVersion` | 488 | String/null | 版本 |
| `Publisher` | 552 | String/null | 发布者 |
| `InstallDate` | 575 | String/null | 安装日期 |
| `EstimatedSizeKb` | 591 | **Int64** | 估算大小 KB |
| `UninstallString` | 591 | String | 卸载命令行 |
| `QuietUninstallString` | 531 | String/null | **静默卸载命令行** |
| `QuietUninstallPossible` | 591 | Boolean | 能否静默 |
| `UninstallPossible` | 591 | Boolean | 能否卸载 |
| `UninstallerKind` | 591 | String | 卸载器类型（Msi/Nsis/InnoSetup/…） |
| `InstallLocation` | 455 | String/null | 安装目录 |
| `Is64Bit` | 591 | String | X64 / X86 |
| `IsProtected` / `IsRegistered` / `IsOrphaned` | 591 | Boolean | 状态标记 |
| `IsUpdate` / `IsValid` / `IsWebBrowser` / `SystemComponent` | 591 | Boolean | 分类标记 |
| `RegistryKeyName` / `RegistryPath` | 345 | String/null | 注册表来源 |
| `BundleProviderKey` | 276 | String/null | 包管理来源 |
| `ParentKeyName` | **1** | String/null | 几乎全空，不可依赖 |
| `Comment` / `AboutUrl` / `InstallSource` / `UninstallerLocation` | 155/92/220/354 | String/null | 补充信息 |

**含义**：`QuietUninstallString` + `QuietUninstallPossible` 让我们能判断
「这个程序能否静默卸载」，这是纯注册表方案做不到的。

---

## 6. 三个必须绕开的坑

### 坑 1 —— `uninstall` 只接受 `.bcul` 文件，不能按名字卸载

源码：`ProcessUninstallCommand` 要求 `args[0]` 是存在的文件，否则
`Invalid path or missing list file`。

**含义**：封装的核心价值就是 **「程序名 → 生成 .bcul → 干跑 → 真跑」**。

### 坑 2 —— `/F=json` 对 `uninstall` 不生效，结果在 stderr

实测 `uninstall probe.bcul /N /F=json`：

```
exit=0  stdout=0 B  stderr=799 B
```

stderr 内容即全部输出：

```
Found 591 applications.
1 application(s) were matched by the list: Acme Archiver 4.10 (x64)
Setting-up for the uninstall task...

Running: 1, Waiting: 0, Finished: 0, Failed: 0
Running: 0, Waiting: 0, Finished: 1, Failed: 0
Uninstall task Finished.
Dry run finished. No changes were made.
```

**含义**：想从 `uninstall` 取结构化结果，**必须解析 stderr**，不能只看 stdout。

### 坑 3 —— `.bcul` 是 XmlSerializer 的 `UninstallList`

源码 `UninstallList.ReadFromFile` → `XmlSerializer(typeof(UninstallList))`。
结构：`UninstallList { Enabled, Filters[] }`，`Filter { Enabled, Exclude, Name, ComparisonEntries[] }`，
`FilterCondition { InvertResults, FilterText, ComparisonMethod }`。

**实测验证**（手写 `.bcul` + `/N` 干跑）：

```xml
<?xml version="1.0" encoding="utf-8"?>
<UninstallList xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <Enabled>true</Enabled>
  <Filters>
    <Filter>
      <Enabled>true</Enabled>
      <Exclude>false</Exclude>
      <Name>cli probe</Name>
      <ComparisonEntries>
        <FilterCondition>
          <InvertResults>false</InvertResults>
          <FilterText>AcmeArchiver</FilterText>
          <ComparisonMethod>Contains</ComparisonMethod>
        </FilterCondition>
      </ComparisonEntries>
    </Filter>
  </Filters>
</UninstallList>
```

→ 干跑命中 `1 application(s) were matched by the list: Acme Archiver 4.10 (x64)`。
**格式已被真机证实可用**，不是猜的。

---

## 7. 由此确定的架构

```
scan   (需管理员, ~60s)  BCU-console list /F=json  →  本地索引
query  (无需管理员, 瞬时)  读本地索引（不再调 BCU）
uninstall (需管理员)      程序名 → 生成 .bcul → /N 干跑 → 确认 → 真跑 → 解析 stderr
```

**为什么不每次查询都调 BCU**：57.9 秒 × 每次查询是不可接受的，
且每次都要 UAC。索引化之后查询是毫秒级。

**为什么卸载必须两阶段**：`/U` 是不可逆的，「先干跑、让调用者看到命中什么、
再真跑」是这个工具唯一负责任的设计。`/U` 只在显式传入时才用。

---

## 8. 与上游的关系

- **BCU 本身**：Apache-2.0，独立程序，**不随本仓库分发**，由 CLI 定位或按需下载
- **本封装**：只调用 BCU 的公开命令行接口，不修改、不重编译 BCU
- `repl_skin.py` 若沿用，来自 HKUDS/CLI-Anything（Apache-2.0），需在 NOTICE 中保留归属
