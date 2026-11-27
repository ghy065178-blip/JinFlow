# 更新日志

产品版本和发布修订由 `src/jsj_desktop/__init__.py`、包元数据及 `update/latest.json`
共同记录。发布前运行 `tools/check_update_channel.py --offline` 校验标签和安装包版本。

## 2.0.0 修订 2（2026-11-27）

相较上一份 `v2.0.0` 发布包，本次涵盖 Apple Silicon、Intel Mac、Windows x86_64 和 Windows ARM64。

### 更新

- 采用液态玻璃参考稿的青紫极光色、圆角玻璃面板、边缘高光与分层背景。黑色、白色及跟随系统主题继续可选。
- 从方案 B 矢量稿重新导出 1,024 × 1,024 像素母图，顶栏按显示缩放选用抗锯齿资源。macOS 和 Windows 系统图标采用同一源稿。

### 新增

- 左栏与实时终端之间增加可拖拽分隔线，左右两栏保留各自的最小宽度。
- 启动时默认在后台检查更新。检测到适用的新版后，顶部显示「更新」。点击打开应用内更新面板，由用户确认下载与安装。面板显示下载、校验、安装和结果。
- Windows 支持 F11 切换全屏和 Esc 返回窗口模式。

### 修复

- 左栏滚轮和触控板按平台换算为像素并合并密集事件。触摸拖动按手指位移滚动，滚动条仍可直接拖动。
- 档案下拉框独占一行，四个操作按钮等宽排布。「删除」紧接在「重命名」右侧。
- Windows 窗口缩放、最大化、还原和全屏切换期间合并布局更新，限制单次事件队列处理时间，并在尺寸稳定后集中刷新状态。提示层随窗口绘制。
- Windows 安装交接显示「正在安装」，独立安装进程完成替换并重启后提示成功，回滚时提示失败。macOS 在新版本启动请求失败时恢复原安装。
- macOS 从源码或只读位置更新时，以完整的 `.app` 保存和启动暂存副本。已重命名的 `.app` 也可原位更新。

### 兼容性与验证

- 产品版本和 GitHub 标签分别为 `2.0.0` 和 `v2.0.0`。旧 2.0.0 可在「帮助 → 检查更新与升级」识别构建 `2.0.0.2`。本机档案、报名信息和任务配置继续使用现有数据目录和格式。
- 回归覆盖档案区域窄宽布局、滚动输入、同版本升级、手动确认与失败回滚。Windows 原生测试覆盖普通窗口缩放、最大化与还原、进入与退出全屏。

## 2.0.0 首次发布（2026-11-27）

### 新增

- 方案 B 应用图标，提供可编辑 SVG 源稿、macOS `app.icns` 和 Windows `app.ico`。
- 玻璃质感视觉令牌，加入分层表面、轻薄描边、内侧高光和柔和阴影，保持现有单页布局与组件位置。
- 设置窗口新增黑色、白色和跟随系统三种主题，旧版 `settings.json` 自动使用跟随系统。
- 主窗口、实时日志、提交预览、设置窗口和更新弹窗统一读取当前主题颜色。
- 顶部北京时间统一使用 `Asia/Shanghai` 时区，按真实时间持续更新，缺少时区数据库时回退到 UTC+8。

### 兼容性

- 表单结构读取、联动规则、`entryAttributes`、校时、等待和冲刺逻辑保持不变。
- 1.0.0～1.0.3 继续共用原有数据目录和配置格式，可直接升级到 2.0.0。
- 运行时仍只依赖 Python 标准库和 tkinter/ttk，玻璃效果使用跨平台组合式表现，不引入平台专属 UI 框架。

## 1.2.0 (2026-11-26)

新增**应用内检查更新与升级**；原有报名业务逻辑、界面呈现与数据格式全部不变。

### 新增
- `src/jsj_desktop/update/`：版本比较（含 `v` 前缀、四段式版本号）、
  多来源更新通道（静态清单 / GitHub Releases API / Release 资产 / 随包兜底）、
  SHA256 校验、四平台安装与切换、异常分类与回滚。
- 「帮助 → 检查更新与升级…」弹窗：显示当前版本、最新版本、适用平台、更新通道
  与版本说明；一键下载 → 校验 → 安装 → 重启；失败用弹窗给出原因与建议，
  且不改动现有版本与报名数据。
- 启动时默认在后台检查新版本。在线检查发现新版本后，主窗口顶部显示对应版本的
  GitHub 发布页按钮。可在「设置与关于」关闭自动检查。
- 命令行：`--check-update`（只读显示版本信息）、`--apply-update`、
  `--no-relaunch`、`--manifest-url`。
- `update/latest.json` 版本无关清单；`tools/generate_update_manifest.py` 在
  Release 时填入真实 SHA256；`tools/check_update_channel.py` 在 CI/Release
  校验版本号、四平台资产与历史版本升级路径。
- `tools/upgrade_legacy.py`（发布资产 `JinFlow-Upgrade-Helper.py`）：
  供 1.0.0～1.0.3 已冻结旧包用户一次性检测、校验并切换到 1.2.0。
- 构建脚本随包打入 `update/latest.json` 与 `APP_VERSION.txt` 版本标记，
  并在打包后校验；Release 工作流上传 `latest.json` 与升级助手。

### 历史版本兼容
- 发布页现有 v1.0.0 / v1.0.1 / v1.0.2 / v1.0.3 全部登记在清单
  `legacy_versions` 与 `legacy_upgrade_paths`，最低可升级版本为 1.0.0。
- 四个版本使用同一用户数据目录与同一 `报名信息.json` / `profiles.json` 格式；
  升级过程不读写这些文件，因此无需数据迁移。
- 说明：已发布的 1.0.x 冻结包内**没有**更新代码，无法凭空获得「应用内检查」；
  其用户按上述升级助手或手动下载 1.2.0 覆盖安装即可。1.2.0 起所有新版本
  均可在应用内直接检查与升级。

### 验证
- 新增 `tests/test_update.py`：版本兼容、清单校验、多通道容错、校验和、
  安装/回滚、界面与 CLI 入口、发布配置一致性，以及用本地 HTTP 服务器模拟
  Release 的端到端「检查 → 下载 → 校验 → 切换到 1.2.0」演练。
- 既有 95 项测试全部继续通过，新增 58 项，全量 **153 项通过**；
  `--self-test`、`check_no_pii --strict`、`check_update_channel --offline` 均通过。

## 1.0.3 (2026-11-26)

macOS 首次启动体验修复（对应反馈：第一次解压出来的 `.app` 提示
「应用程序 "JinshujuDesktop.app" 无法打开」，再解压 / 复制一次却正常）。

### 诊断
- 检查 v1.0.2 的 `JinFlow-macos-arm64.zip`：433 个条目均为 Unix
  条目，可执行文件 `Contents/MacOS/JinshujuDesktop` 权限 0755、19 个符号
  链接完整、CA 根证书与 `_CodeSignature` 齐全，**归档与二进制没有损坏**；
  CI 也实机执行过 `--check-tls`。
- 根因在 macOS 分发环节：浏览器下载的 zip 带 `com.apple.quarantine`，
  从解压目录直接双击未公证 `.app` 会触发 Gatekeeper / App Translocation
  （只读随机路径运行）；截图中目录位于 iCloud 云盘桌面且提示「iCloud 储存
  空间已满」、文件名带云朵图标，说明 430 个文件组成的 bundle 当时可能仍是
  云端占位符，LaunchServices 因此报通用「应用程序无法打开」。重新解压或
  复制得到完整本地副本后即可正常启动，与现象一致。

### 修复
- macOS 目标同时产出 **DMG**（单文件只读映像，含「应用程序」拖放快捷方式）
  与原有 zip；Release 页面与包内 `README-RELEASE.txt` 明确引导「拖入应用程序
  后再打开」，不要直接在下载目录 / iCloud 桌面双击。
- `stage_and_pack` 复制 `.app` 后重做 ad-hoc 签名并 `codesign --verify`，
  保证 `CodeResources` 与最终 bundle 一致。
- `check_no_pii` 支持 `.dmg`：在 macOS 上挂载后 `scan_tree`，挂载失败即失败。
- CI 新增 `Verify macOS distribution (user flow)`：模拟用户解压 zip 与挂载
  DMG，分别检查可执行位、`codesign --verify --deep --strict` 并实跑
  `--check-tls`；`SHA256SUMS.txt` 覆盖 zip 与 dmg。
- 新增 10 项分发回归测试；全量 95 项通过。

### 仍无法在 Windows 侧根治
- Apple Developer ID 签名与公证必须在 macOS 上用付费开发者账号完成；
  在此之前 Gatekeeper 提示仍需用户手动允许或 `xattr -dr com.apple.quarantine`。

---

## 1.0.2 (2026-11-26)

macOS 版 HTTPS 证书链修复（对应反馈：Mac 上「读取表单」失败、软件无法正常使用）。

### 修复
- 根因：macOS 的 Python/OpenSSL **不读取系统钥匙串**；PyInstaller 冻结后
  `ssl.get_default_verify_paths()` 仍指向构建机路径，用户机器上不存在该 CA 文件，
  所有 HTTPS 请求报 `CERTIFICATE_VERIFY_FAILED: unable to get local issuer
  certificate`。Windows 走系统证书存储，因此只有 macOS 版受影响。
- `packaging/build.py`：构建时用 `certifi` 的 CA bundle，随包加入 `certs/cacert.pem`；
  打包后强制校验归档内确实存在该文件，缺失直接构建失败。
- `packaging/entry_point.py`：冻结版 macOS 启动时设置 `SSL_CERT_FILE` 指向随包证书
  （兼容 Resources / Frameworks 两种 PyInstaller 6 布局，并有系统路径兜底）。
- `requirements-dev.txt` 增加 `certifi`（仅构建依赖，运行时仍零第三方依赖）。
- 新增 `--check-tls` 诊断命令：只读 GET，输出 CA 路径并验证 HTTPS 证书链，不提交任何数据。

### 验证
- 新增 9 项证书链回归测试；全量 85 项通过；`--check-tls` 实测 TLS 验证通过。
- Release 工作流增加 macOS 冻结应用的 `--check-tls` 实机验证。

---

## 1.0.1 (2026-11-26)

滚动体验修复（对应截图反馈：左栏只能通过拖动滚动条移动）。

### 修复
- 左栏 `ScrollableFrame` 原先只给容器自身绑定滚轮，事件落到子控件后不会冒泡，
  导致参数区与个人信息区无法用滚轮滚动。改为给整棵子树追加唯一 `bindtag`，
  在 tag 上统一处理，动态重建字段控件后重新挂载（幂等）。
- 新增鼠标滚轮（Windows/macOS）、触控板细粒度 delta 自适应滚动、
  Linux `<Button-4/5>`，以及触摸屏按住空白处拖拽平移。
- 保持原有布局、滚动条拖动与联动不变；右侧实时终端、输入框、下拉框、复选框、
  按钮等交互不受影响（不使用全局 `bind_all`）。

### 验证
- 新增 13 项滚动回归测试（无 tkinter 环境自动跳过逻辑用例，静态检查仍执行）；
  全量 73 项测试通过，GUI 冒烟（滚轮/触控板/触摸/区域隔离/滚动条/输入交互）通过。

---

## 1.0.0 (2026-11-26)

首个可发布版本。

### 新增
- 将旧版 `auto_submit.py` + `control_panel.py/html` 整理为可发布到 GitHub 的
  跨平台桌面项目，源码位于 `src/jsj_desktop/`。
- 基于 tkinter/ttk 的原生图形界面：与旧版 `control_panel.html` 完全一致的单页深色布局
  （header / 多开任务栏 / 5 张状态卡 / 左栏运行配置+报名信息 / 右栏实时终端）；
  不再需要终端、`.bat`、本地 HTTP 服务或浏览器。逐项对照见 `docs/UI_PARITY.md`。
- 本地多人档案：新建 / 应用切换 / 更新 / 重命名 / 删除 / 导入 / 导出。
- 最多 8 个独立任务，各自独立配置目录、时间参数与日志。
- 旧版数据迁移：图形界面与 `tools/migrate_legacy.py` 支持
  `报名信息.json`、`个人档案.json`、`多开任务/*/报名信息.json`。
- 演练预览表、停止当前/全部任务、日志脱敏显示、北京时间与状态卡。
- 四平台发布流水线：Intel Mac、Apple Silicon Mac、Windows x86_64、Windows ARM64。
- 界面一致性：补齐每任务独立 ↻ 刷新、档案下拉、连接状态 pill、右下角 toast，
  并按原面板全部文案/按钮/行为建立静态回归测试。
- 隐私扫描器：豁免 PyInstaller 随包携带的 Tcl/Tk 编码表（`.enc` 长数字表格），
  避免 Release 构建误报；文件名禁用检查仍生效，并补充两项发布包回归测试。
- 敏感数据扫描器 `tools/check_no_pii.py`，覆盖仓库、CI 与发布包。
- 60 项单元测试，含与旧版参考实现的逐函数等价性对照、黄金数据断言与界面一致性回归。

### 变更
- 业务逻辑拆分为 `core/` 纯函数层；`print`/`input` 改为事件与可注入应答源，
  提交数据、请求体、校时、等待与冲刺判定保持不变。
- 多开任务由「子进程 + stdout 抓取」改为「独立线程 + 结构化事件」，隔离由
  独立配置目录保证。
- 移除内置的真实活动表单 token；首次使用需填写链接，之后复用本地上次链接。

### 隐私
- 仓库与发布包不含 `报名信息.json`、`个人档案.json`、备份、日志、
  `panel_url.txt`、`多开任务/` 或任何真实个人信息。
- 测试数据与示例全部为合成占位值。
