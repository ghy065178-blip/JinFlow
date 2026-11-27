# 构建与发布要求（四平台）

## 1. 目标平台矩阵

| 发布包 | CPU 架构 | 构建 runner | 官方 Python | 产物 |
|---|---|---|---|---|
| `JinFlow-macos-x86_64.dmg` + `.zip` | Intel Mac (x86_64) | `macos-15-intel` / `macos-26-intel` | CPython 3.11+（x86_64） | `JinshujuDesktop.app`（DMG 推荐） |
| `JinFlow-macos-arm64.dmg` + `.zip` | Apple Silicon (arm64) | `macos-15` / `macos-26` / `macos-latest` | CPython 3.11+（arm64） | `JinshujuDesktop.app`（DMG 推荐） |
| `JinFlow-windows-x86_64.zip` + `JinFlow-windows-x86_64-Setup.exe` | Windows AMD64 | `windows-2022` / `windows-2025` | CPython 3.11+（amd64） | 支持安装、启动和卸载 |
| `JinFlow-windows-arm64.zip` + `JinFlow-windows-arm64-Setup.exe` | Windows ARM64 | `windows-11-arm` | CPython 3.11+（arm64，3.11 起提供） | 支持安装、启动和卸载 |

> PyInstaller **不是交叉编译器**：ARM64 包必须在 ARM64 机器上构建。不要用 x64 runner 加 `--target-arch` 伪造平台包，也不要把 x64 包改名冒充 ARM64。
> `windows-11-arm` 托管 runner 对**公开仓库**免费；私有仓库需更大的付费 runner 或自托管 Windows ARM64 代理。

## 2. 前置条件

- **Python 3.11+**（Windows ARM64 从 3.11 才有官方安装包；推荐 3.12）。
- 安装时勾选 **Tcl/Tk and IDLE**（tkinter 依赖）；嵌入式/精简版 Python 不含 Tk，不能用于 GUI 构建。
  ```bash
  python -c "import tkinter; print(tkinter.TkVersion)"   # 必须成功
  ```
- **PyInstaller 6.10+**（官方支持 Windows x64/ARM64、macOS x86_64/arm64）：
  ```bash
  python -m pip install -r requirements-dev.txt
  ```
- 运行时**不需要**任何第三方包；打包时只把标准库 + 本项目源码 + 合成测试样例打进去。
- 构建前必须通过：
  ```bash
  python -m unittest discover -s tests -t . -v
  python tools/check_no_pii.py --strict
  python -m jsj_desktop --self-test
  ```

## 3. 本地构建

```bash
python packaging/build.py                     # 自动识别当前系统/架构
python packaging/build.py --target macos-arm64 --sign-identity "Developer ID Application: ..."
python packaging/build.py --target windows-x86_64 --version 2.0.0
```

`build.py` 会：

1. 校验 Python / tkinter / PyInstaller 与目标架构是否匹配；
2. 调用 `pyinstaller --noconfirm --clean --onedir --windowed --name JinshujuDesktop`，
   macOS 附加 `--osx-bundle-identifier`，Windows 附加 `--version-file`；
3. 把 `tests/fixtures/sample_form.json` 作为只读样例数据加入（供 `--self-test` 使用），
   并把 `update/latest.json` 与 `APP_VERSION.txt` 版本标记打入包内（1.2.0 起，
   打包后由 `verify_manifest_in_archive()` 强制校验）；
4. 可选图标 `packaging/icons/app.icns`（macOS）/ `app.ico`（Windows）；缺失则使用系统默认图标；
5. macOS 用 `ditto -c -k --keepParent` 保留 `.app` 内的符号链接，Windows 用 zip 打包 onedir；
6. 写入 `BUILD_INFO.txt`（版本、系统、架构、Python、构建时间、Git commit）与 `SHA256SUMS.txt`；
7. 调用 `tools/check_no_pii.py --strict --artifact <归档>`，发现问题直接失败。

输出目录：`dist/<target>/`。

## 4. CI / GitHub Actions

### `ci.yml`（每次 push / PR）

矩阵覆盖 `ubuntu-latest`、`windows-2022`、`windows-11-arm`、`macos-15-intel`、`macos-15`；每个 job：

- `actions/setup-python@v6`（在 ARM64 runner 上自动选 arm64 Python）；
- `python -m compileall -q src`；
- `python -m unittest discover -s tests -t . -v`；
- `python tools/check_no_pii.py --strict`；
- `python -m jsj_desktop --self-test`；
- 图形依赖检查（非致命，Linux 精简镜像可能无 Tk）。

### `release.yml`（推送 `v*` 标签）

四个原生 runner 构建并上传产物。`release` job 核对各平台包、生成 `SHA256SUMS.txt`，然后更新 GitHub Release。
覆盖现有发布时，可在待发布的分支上手动运行 Release 工作流并指定 `tag=v2.0.0`。
该工作流先完成四平台构建及校验，再替换同名资产、更新标签和发布说明。

```bash
git tag -a v1.0.0 -m "1.0.0"
git push origin v1.0.0
```

## 5. 签名、公证与系统提示

### macOS（两个包都适用）

- 开发/自测：
  ```bash
  codesign --force --deep --sign - --entitlements packaging/entitlements.plist \
           dist/.../JinshujuDesktop.app
  ```
  这属于 **ad-hoc 签名**，能解决部分「已损坏」提示，但 **Gatekeeper 仍会拦截**未公证的包。
- 正式对外发布（推荐）：
  1. 使用 **Developer ID Application** 证书签名（`--options runtime` 启用 hardened runtime）；
  2. `xcrun notarytool submit <zip> --apple-id ... --team-id ... --password ... --wait` 公证；
  3. `xcrun stapler staple JinshujuDesktop.app`；
  4. 用 `ditto` 重新打包并验证 `spctl -a -vvv JinshujuDesktop.app`。
- 需要 Apple Developer 账号；公证凭据通过 GitHub Secrets 注入，切勿写入仓库。
- 未签名/未公证包需在 Release 说明中提示用户「系统设置 → 隐私与安全性 → 仍要打开」。

### Windows（两个包都适用）

- 建议用 OV/EV 代码签名证书对 `JinshujuDesktop.exe` 及打包后的安装器签名：
  ```powershell
  signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a JinshujuDesktop.exe
  ```
- 未签名包首次运行会出现 **SmartScreen** 蓝色提示，属正常现象；请在 Release 说明中写明。
- Windows ARM64 包只能在 ARM64 设备（或 ARM64 runner）上运行验证。

## 6. 发布包内容检查

发布前逐项确认：

- [ ] 包内**没有** `报名信息*.json`、`个人档案*.json`、`*.backup.json`、`panel_url.txt`、`*.log`、`多开任务/`；
- [ ] `tools/check_no_pii.py --strict --artifact <归档>` 通过；
- [ ] `BUILD_INFO.txt` 中的架构与包名一致，且包含 `APP_VERSION.txt` 版本标记；
- [ ] `update/latest.json` 的 `tag` 与 `__version__` 一致，构建号与 `release_revision` 对应，
      `legacy_upgrade_paths` 覆盖 1.0.0～1.0.3；
- [ ] `python tools/check_update_channel.py --offline --checksums dist/SHA256SUMS.txt` 通过；
- [ ] Release 资产包含 `latest.json` 与 `JinFlow-Upgrade-Helper.py`；
- [ ] `SHA256SUMS.txt` 已生成并随 Release 上传；
- [ ] 在目标架构的机器上双击启动，确认无控制台窗口、单页面板与原控制面板一致、`--self-test` 可执行；
- [ ] 首次启动后数据目录为空（没有预置任何档案）；
- [ ] README / LICENSE / CHANGELOG 随仓库提供，Release 说明写明平台、签名状态与合规声明。

## 7. 常见问题

| 问题 | 原因 / 处理 |
|---|---|
| `No module named tkinter` | Python 未装 Tcl/Tk；换用官方安装包并勾选相应组件 |
| PyInstaller 在 Windows ARM64 找不到 bootloader | 升级到 PyInstaller 6.10+；必要时从源码构建 bootloader |
| macOS `.app` 体积异常大 | zip 未保留符号链接；必须使用 `ditto`/`zip -y`，不要普通 `shutil.make_archive` |
| macOS 提示「已损坏，无法打开」 | 未签名/未公证，或下载时带了 quarantine 属性；按第 5 节签名公证 |
| macOS 提示「应用程序 … 无法打开」，但再解压一次就正常 | 下载隔离（quarantine / App Translocation）+ iCloud 云盘同步未完成导致 bundle 内容不完整。1.0.3 起提供 DMG 并引导拖入「应用程序」；`stage_and_pack` 复制后重做 ad-hoc 签名；CI 新增「解压 zip → 启动」「挂载 DMG → 启动」用户流程验证 |
| Windows 提示 SmartScreen | 未做代码签名；用证书签名或提示用户手动放行 |
| 构建产物被 PII 扫描拦截 | 检查是否把本地数据目录误加进 `--add-data`；只应包含 `tests/fixtures/` 合成样例。Tcl/Tk 编码表已列入运行时数据豁免，若仍有误报见 `docs/PRIVACY.md` |
| macOS 版能开窗口但读取表单报 `CERTIFICATE_VERIFY_FAILED` | macOS 的 Python/OpenSSL 不读系统钥匙串，冻结包必须携带 `certs/cacert.pem`（构建脚本已强制校验）。1.0.2 起由 `packaging/entry_point.py` 设置 `SSL_CERT_FILE`；用 `--check-tls` 诊断 |
| DMG 挂载失败 / PII 扫描报「发布包既不是目录也不是有效 zip」 | `check_no_pii.scan_artifact` 对 `.dmg` 会在 macOS 上用 `hdiutil attach -readonly -nobrowse` 挂载后 `scan_tree`；只在 macOS 构建 DMG，Windows 上不生成 |
| 私有仓库 `windows-11-arm` 无法启动 | 该托管 runner 仅对公开仓库免费；改用自托管 ARM64 runner |

## 8. 版本与变更

- 产品版本为 **2.0.0**，发布修订为 **2**。源码、Python 包元数据和标签记录产品版本。
  冻结包的 `APP_VERSION.txt` 首行与更新清单记录构建号 `2.0.0.2`，供已发布客户端比较和校验。
  `APP_VERSION.txt` 的 `Version:` 行提供新版界面使用的产品版本。发布前运行 `tools/check_update_channel.py --offline` 校验版本配置。
- 任何涉及 `core/` 业务逻辑的改动，都必须保证 `tests/test_legacy_parity.py` 与
  `tests/test_mapping.py` 继续通过；1.2.0 只新增 `update/` 与界面附加入口，
  未改动 `core/` 任何一行。

## 9. 应用内更新发布配置（2.0.0）

发布 `v2.0.0` 时，`release.yml` 在四个原生 runner 构建完成、汇总校验和后执行以下步骤。

1. `tools/generate_update_manifest.py --checksums release-assets/SHA256SUMS.txt
   --output release-assets/latest.json`：把 4 个 zip + 2 个 dmg 的真实 SHA256
   写入清单；缺少任一平台资产直接失败，避免发出不完整的更新通道。
2. `tools/check_update_channel.py --offline --checksums ...`：再次核对版本、
   四个平台 ZIP/DMG 资产、历史版本升级路径与校验和覆盖。Windows setup.exe
   由 Inno Setup 构建，并通过同一 Release 一并发布。
3. 复制 `tools/upgrade_legacy.py` 为
   `release-assets/JinFlow-Upgrade-Helper.py`，随 Release 上传。
4. GitHub CLI 更新四个平台的八个安装资产和升级助手，随后更新 `SHA256SUMS.txt`、`latest.json` 及发布说明。

```bash
python tools/check_update_channel.py --offline
git tag -a v2.0.0 -m "2.0.0 玻璃质感界面与主题控制"
git push origin v2.0.0
```

原 2.0.0 在应用内更新面板识别 `2.0.0.2`，替换后的客户端显示 2.0.0 修订 2。
四平台更新回归见 `tests/test_update.py`，Windows 模式验证见 `tests/test_window_transition.py`。
