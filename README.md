# 金数据报名助手 · 桌面版

把原有的「金数据自动提交脚本 + 浏览器控制面板」改造为一个**可直接发布到 GitHub 的跨平台桌面软件项目**：

- 保持原有内置功能、业务逻辑与数据处理结果不变（`entryAttributes`、GraphQL 请求体、联动取舍、校时与冲刺判定均与原脚本一致，并有等价性测试背书）；
- 交互升级为 **tkinter/ttk 原生图形窗口**，界面呈现、操作入口、交互逻辑与功能行为与文件夹内原「可视化操控面板」逐项一致；不再需要终端窗口、`.bat` 启动器、本地 HTTP 服务或浏览器标签页；
- 所有报名信息与多人档案只写在**本机用户数据目录**，仓库与发布包不含任何内置个人信息、真实活动链接或日志；
- 支持在本地**保存 / 管理 / 读取 / 切换多人信息**，并保留最多 8 个独立任务；
- 目标平台：**Intel Mac (x86_64)、Apple Silicon Mac (ARM64)、Windows x86_64/AMD64、Windows ARM64**。

> 运行时零第三方依赖，只需要 Python 3.11+ 标准库（含 Tcl/Tk）。
> 本项目不是金数据官方产品，仅适用于**未启用验证码**的表单，请遵守平台服务条款与活动规则。

---

## 1. 目录结构

```
jinshuju-registration-desktop/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                  # 四平台 + Linux 的测试 / PII 扫描矩阵
│   │   └── release.yml             # 四平台发布包构建与 GitHub Release
│   └── ISSUE_TEMPLATE/bug_report.yml
├── .gitignore / .gitattributes     # 屏蔽个人信息、备份、日志、构建产物
├── LICENSE / CHANGELOG.md / CONTRIBUTING.md
├── README.md                       # 本文件
├── pyproject.toml                  # 包元数据与 gui-scripts 入口
├── requirements-dev.txt            # 仅构建/测试依赖（运行时不需要）
├── src/jsj_desktop/
│   ├── __init__.py / __main__.py / app.py     # 入口：GUI 默认 / CLI 可选 / 自检
│   ├── core/                       # 与界面解耦的业务逻辑（等价旧脚本）
│   │   ├── constants.py            # 常量、GraphQL CHECK_QUERY / MUTATION
│   │   ├── endpoint.py             # 链接解析、HTTP、表单结构拉取
│   │   ├── rules.py                # 联动显示规则求值
│   │   ├── mapping.py              # 配置↔chosen、build_attributes、填写流程
│   │   ├── submit.py               # 校时、请求体、提交结果判定
│   │   └── engine.py               # 主流程编排（等待 / 冲刺 / 停止）
│   ├── data/                       # 本地数据层
│   │   ├── paths.py                # 跨平台用户数据目录
│   │   ├── config_store.py         # 报名信息.json 读写 + 自动备份
│   │   ├── profile_store.py        # 多人档案 CRUD / 切换 / 导入导出
│   │   └── settings_store.py       # 界面偏好与任务元信息
│   ├── tasks/manager.py            # 最多 8 个独立任务、事件队列、启停与应答
│   └── ui/                         # 原生图形界面
│       ├── theme.py / widgets.py   # 复刻原面板 CSS 的深色主题、状态卡、滚动容器、彩色日志
│       └── main_window.py          # 与原面板一致的单页主窗口（含菜单/弹窗附加入口）
├── tests/                          # 73 项单元测试（含界面一致性）+ 合成样例
│   └── fixtures/                   # 合成 GraphQL 响应与黄金数据
├── legacy/auto_submit_reference.py # 旧脚本只读参考副本（已移除内置 token）
├── examples/                       # 占位符示例档案（非真实数据）
├── docs/
│   ├── ARCHITECTURE.md             # 架构与数据流
│   ├── FEATURE_PARITY.md           # 原功能 → 新界面逐项对照
│   ├── UI_PARITY.md                # 主界面 ↔ 原可视化操控面板一致性对照
│   ├── USER_GUIDE.md               # 图形界面使用手册
│   ├── CONFIGURATION.md            # 配置、数据格式与环境变量
│   ├── PRIVACY.md                  # 隐私与敏感数据防护
│   ├── MIGRATION.md                # 从旧脚本迁移数据
│   └── RELEASE.md                  # 四平台构建、签名、公证与发布要求
├── packaging/
│   ├── build.py                    # PyInstaller 构建 + 打包 + PII 扫描
│   ├── entitlements.plist          # macOS 签名 entitlements
│   ├── version_info.txt            # Windows 可执行文件版本资源
│   ├── make_dmg.sh                 # 可选：生成 macOS DMG
│   └── icons/README.md             # 可选图标放置说明
└── tools/
    ├── check_no_pii.py             # 仓库/发布包敏感数据扫描器
    ├── migrate_legacy.py           # 旧版数据导入（命令行）
    └── smoke_test.py               # 无界面整体自检
```

---

## 2. 界面功能范围

主窗口与文件夹内原 `control_panel.html` 可视化操控面板**完全一致**：同样的深色配色、单页布局与全部操作入口。逐项对照见 `docs/UI_PARITY.md`，并由 `tests/test_ui_parity.py` 固化回归。

| 区域 | 功能 |
|---|---|
| **header / 任务栏 / 状态卡** | 品牌 + 连接状态 + 北京时间；多开任务标签（每个带独立 ↻ 刷新）+ 新建 / 关闭 / 刷新；5 张实时状态卡（运行状态、倒计时、提交尝试、服务器时钟偏差、最新反馈） |
| **左栏 · 运行配置** | 表单链接输入与「读取表单」；表单名称/状态/开放时间/验证码/字段数；快速模式 `--quick`、仅演练 `--dry-run`、自动应答终端提问；开放时间来源（表单时间 / 手动指定 / 立即提交）与手动时间；提前量、提交间隔、冲刺时长；启动 / 演练自检 / 停止 |
| **左栏 · 报名信息** | 按在线表单结构**动态生成**字段控件（单选下拉、多选/文本输入、可选项提示、必填标记）；按联动规则实时显隐；保存 / 重新载入；个人信息档案下拉支持**新建、应用切换、更新、重命名、删除、导入、导出、从旧版文件夹导入** |
| **右栏 · 实时终端** | 彩色分级日志、自动滚动、清空、导出日志、等待输入提示、手动输入行与快捷应答按钮（回车 / 1 / 2 / 3 / m / q） |

附加能力不占主界面，放在菜单栏与弹窗：文件（旧版数据导入、档案导入导出、打开数据目录、退出）、任务（预览提交数据、新建/重命名/关闭/停止全部）、帮助（使用说明、设置与关于、隐私、关于）；「设置与关于」内含日志脱敏、逐项确认、运行环境与合规声明，另有「本次将提交的信息」预览弹窗。

**不再需要**：终端窗口常驻、`.bat` 双击启动、`http://127.0.0.1:8765`、SSE、子进程 stdout 抓取与正则猜测提示语。所有操作都在原生窗口中完成。

---

## 3. 快速开始

### 源码运行

```bash
# 需要 Python 3.11+，且安装时勾选 Tcl/Tk（官方安装包默认包含）
python -m pip install -e .        # 可选；也可直接设置 PYTHONPATH=src
python -m jsj_desktop             # 启动图形界面（默认）
```

跨平台一键（不用安装包也可）：

```bash
PYTHONPATH=src python -m jsj_desktop          # macOS / Linux
set PYTHONPATH=src && python -m jsj_desktop   # Windows CMD
```

### 可选终端模式与自检

```bash
python -m jsj_desktop --self-test             # 无界面、无网络逻辑自检
python -m jsj_desktop --cli --link https://jsj.top/f/xxxxx --dry-run
python tools/smoke_test.py                    # 自检 + 全量单元测试
python -m unittest discover -s tests -t . -v
python tools/check_no_pii.py --strict         # 敏感数据扫描
```

### 发布包

在 [Releases](../../releases) 下载对应平台的 zip / dmg，解压后双击可执行文件即可；**无需安装 Python**。

---

## 4. 配置与本地数据

所有数据都写到当前用户的标准数据目录（可用 `JSJ_DATA_DIR` 覆盖）：

| 平台 | 默认目录 |
|---|---|
| Windows x86_64 / ARM64 | `%APPDATA%\JinshujuDesktop\` |
| macOS Intel / Apple Silicon | `~/Library/Application Support/JinshujuDesktop/` |
| Linux | `$XDG_DATA_HOME/jinshuju-desktop/` 或 `~/.local/share/jinshuju-desktop/` |

```
<数据目录>/
├── settings.json                    # 界面偏好、任务列表、任务绑定的档案
├── profiles.json                    # 多人档案库（与旧版「个人档案.json」格式兼容）
├── profiles.backup.json             # 写入前自动备份
└── tasks/
    ├── t1/报名信息.json             # 主任务配置（按字段中文标签存储，格式不变）
    ├── t1/报名信息.backup.json
    ├── t2/报名信息.json             # 每个任务独立配置与时间
    └── ...
```

- 「报名信息.json」仍以**字段中文标签**为键，并含 `表单链接`；旧版配置可直接导入。
- 「profiles.json」结构：`{"active":"p1","profiles":[{"id":"p1","name":"…","values":{"姓名":"…"}}]}`。
- 写入均采用「先备份 + 临时文件 + 原子替换」，多任务并发写互不覆盖。
- 桌面版**不再内置任何活动 token**：首次使用需填写本次表单链接；之后回车/留空会复用本地保存的上次链接。
- 从旧版迁移：菜单「文件 → 导入旧版数据…」选择旧脚本文件夹，可一次性导入 `报名信息.json`、`个人档案.json` 以及 `多开任务/*/报名信息.json`（每个目录转成一套档案）。详见 `docs/MIGRATION.md`。

---

## 5. 目标平台与发布要求

| 发布包 | 架构 | GitHub Actions runner | 说明 |
|---|---|---|---|
| `JinshujuDesktop-macos-x86_64.zip` | Intel Mac | `macos-15-intel` / `macos-26-intel` | 原生 x86_64，Rosetta 不需要 |
| `JinshujuDesktop-macos-arm64.zip` | Apple Silicon | `macos-15` / `macos-26` | 原生 arm64 |
| `JinshujuDesktop-windows-x86_64.zip` | Windows AMD64 | `windows-2022` / `windows-2025` | 原生 x64 |
| `JinshujuDesktop-windows-arm64.zip` | Windows ARM64 | `windows-11-arm` | 原生 ARM64，Python 3.11+ |

构建要点（完整说明见 `docs/RELEASE.md`）：

1. **PyInstaller 6.10+ 必须在目标架构本机构建**（不是交叉编译器）。四平台各用一个原生 runner，禁止用 x64 runner 交叉产出 ARM64 包。
2. 使用官方 CPython 3.11+（Windows ARM64 从 3.11 起提供官方安装包），并确认包含 **Tcl/Tk**；运行时不需要 pip 安装任何包。
3. 构建产物用 `--onedir --windowed`，macOS 生成 `.app`，Windows 生成无控制台窗口的目录。
4. 每次构建都执行 `tools/check_no_pii.py --strict --artifact <发布包>`，并生成 `SHA256SUMS.txt`。
5. **macOS**：正式对外发布需 Apple Developer ID 签名 + 公证（notarization）；未签名包会触发 Gatekeeper 拦截，需用户手动「仍要打开」。
6. **Windows**：未签名包会触发 SmartScreen 提示；建议用 EV/OV 代码签名证书签名。
7. `windows-11-arm` runner 对公开仓库免费；私有仓库需更大的付费 runner 或自托管 ARM64 代理。

---

## 6. 业务逻辑不变与验证

原脚本的核心算法被逐行搬到 `src/jsj_desktop/core/`，只把 `print()` 换成事件、把 `input()` 换成可注入应答源：

- 表单结构动态拉取（`CHECK_QUERY`）、联动规则求值（含 `and` 矛盾分支退化）、只提交当前可见字段；
- `config_to_chosen` / `chosen_to_config` / `build_attributes` 产出完全相同的 `entryAttributes`；
- `calibrate_clock` 6 次采样取中位数、`build_input` 的 `fillingDuration`、`submit_once` 的 success / wait / fatal / net / maybe 判定；
- 等待心跳、提前量 `-6`、间隔 `0.05`、时长 `40`、冲刺随机抖动、重复提交保护与 `--quick` / `--dry-run` 语义。

`tests/test_legacy_parity.py` 直接加载 `legacy/auto_submit_reference.py`（旧脚本只读副本，仅移除了内置活动 token），逐项比对输出；`tests/test_mapping.py` 用黄金数据断言最终提交值。当前共 **73 项测试全部通过**。

> 唯一有意的业务差异：移除了内置的某次真实活动表单 token（隐私要求）。用户填写链接后，行为与「回车=使用上次链接」保持一致。

---

## 7. 隐私与敏感数据

- 仓库与发布包**不含** `报名信息.json`、`个人档案.json`、备份、日志、`panel_url.txt`、`多开任务/`、真实表单 token 或任何真实姓名/学号/电话。
- `tests/fixtures/` 与 `examples/` 只有合成数据和占位符（`<姓名占位>` 等）。
- `tools/check_no_pii.py` 在 CI、发布前与打包脚本中强制执行；同时检查「禁止文件名、真实链接、内置 token、手机号、身份证号、非占位的个人信息键、硬编码凭据」。
- 运行日志默认只在内存中；导出的日志、档案文件由用户显式选择保存位置。可勾选「日志脱敏显示」（只影响显示，不影响提交数据）。
- 详见 `docs/PRIVACY.md`。

---

## 8. 合规与免责声明

本项目沿用原脚本的纯接口提交方式，**仅在表单未启用验证码时可用**。请仅用于本人合法报名，遵守目标平台服务条款、活动规则与当地法律，勿用于批量刷单、绕过限制或干扰服务。软件按 MIT 许可「按原样」提供，作者不对报名结果、账号状态或平台规则变化负责。

---

## 9. 常见问题

**Q：启动时报 `No module named tkinter`？**
A：使用 python.org 官方安装包并勾选「tcl/tk and IDLE」；部分精简版/嵌入式 Python 不含 Tk。也可用 `--cli` 临时运行。

**Q：表单启用了验证码？**
A：纯接口提交不可用，控制台会提示并停止，请在网页端手动填写。

**Q：多人报名怎么操作？**
A：在左栏「报名信息」为每人存一套档案；点「+ 新建任务」，各任务选择不同档案、设置不同时间，可同时运行（最多 8 个）。

**Q：升级后旧数据会丢吗？**
A：不会。旧版文件保持原样，用菜单「导入旧版数据…」或 `tools/migrate_legacy.py` 复制到新的用户数据目录即可。
