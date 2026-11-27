# JinFlow 2.0.0 UI、窗口过渡与更新修订 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变报名、任务和安装器行为的前提下，改进四平台 UI 交互，修复 Windows 窗口切换重绘问题，并让同版本替换发布可被应用内更新识别。

**Architecture:** 继续使用现有 tkinter/ttk 主窗口和标准库更新服务。左栏放入可拖拽的横向分栏，滚动容器使用像素增量和合帧，窗口 Configure 事件使用短延迟合并。更新清单以 `release_revision` 补足同版本发布比较，顶部按钮打开现有更新面板完成用户确认后的下载和安装。

**Tech Stack:** Python 3.11+ 标准库、tkinter/ttk、unittest、现有 PyInstaller/Windows Inno Setup/GitHub Actions 发布链。

**执行记录** 实际发布以 `docs/releases/v2.0.0.md` 为准。已发布客户端只识别数字版本，因此安装包和公开清单使用四段构建号，应用界面保持 2.0.0。真实 macOS 发布包复测后补充了暂存 `.app` 启动修复，对应修订 2。

---

## Task 1: 为同版本发布增加可比较的修订号

**Files:**
- Modify: `src/jsj_desktop/__init__.py`
- Modify: `src/jsj_desktop/update/version.py`
- Modify: `src/jsj_desktop/update/manifest.py`
- Modify: `src/jsj_desktop/update/client.py`
- Modify: `update/latest.json`
- Test: `tests/test_update.py`

- [ ] **Step 1: 写同版本修订号的失败测试**

在 `tests/test_update.py` 的 `VersionCompatibilityTest` 中加入：

```python
    def test_same_version_higher_release_revision_is_newer(self):
        plan = vmod.upgrade_plan("2.0.0", "2.0.0", current_revision=0,
                                 latest_revision=1)
        self.assertTrue(plan["update_available"])
        self.assertFalse(plan["is_legacy"])
        self.assertEqual(plan["current_revision"], 0)
        self.assertEqual(plan["latest_revision"], 1)

    def test_same_version_same_release_revision_is_current(self):
        plan = vmod.upgrade_plan("2.0.0", "2.0.0", current_revision=1,
                                 latest_revision=1)
        self.assertFalse(plan["update_available"])
        self.assertIn("最新", plan["reason"])
```

在 `ManifestTest` 中加入：

```python
    def test_manifest_normalizes_release_revision(self):
        data = mf.validate_manifest(dict(synthetic_manifest(),
                                         release_revision="3"))
        self.assertEqual(data["release_revision"], 3)
```

- [ ] **Step 2: 运行失败测试**

运行 `PYTHONPATH=src python -m unittest tests.test_update.VersionCompatibilityTest tests.test_update.ManifestTest -v`。预期新增测试因为 `upgrade_plan` 不接受修订参数或清单没有规范化字段而失败。

- [ ] **Step 3: 实现最小修订号比较**

在 `src/jsj_desktop/__init__.py` 增加 `__release_revision__ = 1`。在 `version.py` 将 `upgrade_plan` 签名扩展为 `current_revision=0, latest_revision=0`，返回两个整数修订号，并在版本号相等且远端修订号更高时设置 `update_available=True`。在 `manifest.py` 将 `release_revision` 规范化为非负整数，缺省为 `0`。

在 `client.ReleaseInfo` 保存 `revision`，`fetch_latest` 的选择键按 `(version_key, revision, quality)` 排序。`check_for_update` 传入当前版本和当前修订号，返回 `current_revision`、`latest_revision`，并把同版本高修订结果标记为可更新。无效修订号抛出 `ManifestError`。

将 `update/latest.json` 增加 `"release_revision": 1`，旧版本字段缺失仍按 `0` 处理。

- [ ] **Step 4: 运行更新测试**

运行 `PYTHONPATH=src python -m unittest tests.test_update.VersionCompatibilityTest tests.test_update.ManifestTest tests.test_update.ClientTest -v`，预期全部通过。

- [ ] **Step 5: 提交**

```bash
git add src/jsj_desktop/__init__.py src/jsj_desktop/update/version.py src/jsj_desktop/update/manifest.py src/jsj_desktop/update/client.py update/latest.json tests/test_update.py
git commit -m "feat: compare same-version release revisions"
```

## Task 2: 改进左栏滚动、分栏和档案按钮布局

**Files:**
- Modify: `src/jsj_desktop/ui/widgets.py`
- Modify: `src/jsj_desktop/ui/main_window.py`
- Test: `tests/test_scroll_input.py`
- Test: `tests/test_ui_parity.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_scroll_input.py` 增加普通滚轮速度和像素拖拽累计断言：

```python
    def test_mouse_wheel_uses_normal_page_speed(self):
        f = frame_with()
        f._on_wheel(wheel_event(delta=-120))
        self.assertEqual(f.canvas.yview_scroll.call_args.args[0], 6)

    def test_touch_pan_preserves_fractional_distance(self):
        f = frame_with()
        f._pan_y = 100
        f._pan_active = True
        f._on_pan_move(SimpleNamespace(y_root=98))
        f._on_pan_move(SimpleNamespace(y_root=90))
        self.assertTrue(f.canvas.yview_scroll.called)
```

在 `tests/test_ui_parity.py` 增加静态断言，要求主窗口含 `PanedWindow`、`sashwidth`、`minsize`、`profile_button_row` 和四个按钮的 `grid` 布局。

- [ ] **Step 2: 运行失败测试**

运行 `PYTHONPATH=src python -m unittest tests.test_scroll_input tests.test_ui_parity -v`。预期失败，因为当前滚轮为 3 units，主窗口没有分栏控件，档案按钮仍与下拉框在同一行。

- [ ] **Step 3: 实现滚动和分栏**

在 `ScrollableFrame` 中把 Canvas 的 `yscrollincrement` 调整为 4。普通滚轮将 `abs(delta)` 按 20 的刻度换算，120 的标准滚轮使用 6 units，最大 12 units，触控板小增量至少使用 1 unit，Linux Button-4/5 使用 6 units。触摸拖拽用 `_pan_remainder` 保存不足一个滚动单位的距离，避免抖动和丢步。Canvas 宽度更新增加 `_canvas_width_after` 和 `_pending_canvas_width`，通过一次 `after_idle` 合并连续 Configure。

在 `MainWindow._build_main` 用 `tk.PanedWindow` 承载 `left_scroll` 和 `term_frame`，配置 `orient=tk.HORIZONTAL`、`sashwidth=7`、`opaqueresize=True`，左侧最小 360 像素，右侧最小 520 像素，初始 sash 位置设为 420 附近。左栏滚动对象、右侧日志对象和已有 `_build_console`、`_build_info`、`_build_logs` 调用保持不变。

在 `_build_info` 让 `profile_sel` 独占 `profile_select_row`，新增 `profile_button_row`，对应用、更新、重命名、删除分别使用 `grid(row=0, column=i, sticky="ew")`，四列配置相同 `weight` 和 `uniform`，删除按钮始终为最后一列。

- [ ] **Step 4: 运行滚动和 UI 测试**

运行 `PYTHONPATH=src python -m unittest tests.test_scroll_input tests.test_ui_parity -v`，预期滚轮、触摸、分栏和档案按钮断言全部通过。

- [ ] **Step 5: 提交**

```bash
git add src/jsj_desktop/ui/widgets.py src/jsj_desktop/ui/main_window.py tests/test_scroll_input.py tests/test_ui_parity.py
git commit -m "fix: smooth left panel scrolling and resizable layout"
```

## Task 3: 增加 Windows 窗口过渡合帧

**Files:**
- Modify: `src/jsj_desktop/ui/main_window.py`
- Modify: `src/jsj_desktop/ui/widgets.py`
- Test: `tests/test_window_transition.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_window_transition.py`，用不创建 Tk 根窗口的桩对象测试过渡控制：

```python
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from jsj_desktop.ui.main_window import MainWindow


class WindowTransitionTest(unittest.TestCase):
    def test_configure_events_are_coalesced(self):
        window = MainWindow.__new__(MainWindow)
        window._window_transition_after = None
        window._window_transition_active = False
        window._window_geometry = None
        window.after = MagicMock(return_value="timer")
        window.after_cancel = MagicMock()
        event = SimpleNamespace(widget=window, width=1200, height=800,
                                x=0, y=0)
        MainWindow._on_window_configure(window, event)
        MainWindow._on_window_configure(window, event)
        self.assertTrue(window._window_transition_active)
        self.assertEqual(window.after.call_count, 2)
        window.after_cancel.assert_called_once_with("timer")

    def test_poll_skips_expensive_render_during_transition(self):
        window = MainWindow.__new__(MainWindow)
        window._window_transition_active = True
        window._last_clock = "2099-01-01 00:00:00"
        window.clock_var = MagicMock()
        window.event_queue = MagicMock()
        window.event_queue.get_nowait.side_effect = __import__("queue").Empty
        window.after = MagicMock()
        window._render_task_tabs = MagicMock()
        window._tick_countdown = MagicMock()
        window.theme_mode = "dark"
        window._last_theme_probe = 0.0
        window.system_mode = "dark"
        window._poll()
        window._render_task_tabs.assert_not_called()
        window._tick_countdown.assert_not_called()
```

- [ ] **Step 2: 运行失败测试**

运行 `PYTHONPATH=src python -m unittest tests.test_window_transition -v`，预期因为没有 `_on_window_configure` 和过渡状态而失败。

- [ ] **Step 3: 实现合帧**

在 `MainWindow.__init__` 初始化 `_window_transition_after`、`_window_transition_active`、`_window_geometry`，并绑定 `self.bind("<Configure>", self._on_window_configure, add="+")`。`_on_window_configure` 只处理根窗口事件，取消上一个 timer 后用 `after(120, self._finish_window_transition)` 重新安排。`_finish_window_transition` 清理 timer、调用一次 `update_idletasks()`、调用左栏的 `refresh_layout()`、重绘任务标签和状态，并清除 active 标记。

在 `_poll` 的时钟分支中，过渡 active 时只更新时间变量，不调用 `_render_task_tabs` 和 `_tick_countdown`。稳定后由 `_finish_window_transition` 补一次 `_render_state` 和 `_update_buttons`。窗口销毁前取消 pending timer。`ScrollableFrame.refresh_layout` 立即应用待处理 Canvas 宽度并重算 scrollregion，正常 Configure 仍走 idle 合帧。

- [ ] **Step 4: 运行窗口过渡测试和现有测试**

运行 `PYTHONPATH=src python -m unittest tests.test_window_transition tests.test_scroll_input tests.test_ui_parity -v`，预期通过。

- [ ] **Step 5: 提交**

```bash
git add src/jsj_desktop/ui/main_window.py src/jsj_desktop/ui/widgets.py tests/test_window_transition.py
git commit -m "fix: coalesce window transition redraws"
```

## Task 4: 提升 Logo 资源和液态玻璃视觉令牌

**Files:**
- Modify: `packaging/icons/app.png`
- Modify: `packaging/icons/README.md`
- Modify: `src/jsj_desktop/ui/main_window.py`
- Modify: `src/jsj_desktop/ui/theme.py`
- Test: `tests/test_macos_distribution.py`
- Test: `tests/test_theme.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_macos_distribution.py` 增加 PNG 尺寸检查：

```python
    def test_runtime_logo_is_high_resolution(self):
        import struct
        data = (ROOT / "packaging" / "icons" / "app.png").read_bytes()
        width, height = struct.unpack(">II", data[16:24])
        self.assertGreaterEqual(width, 512)
        self.assertGreaterEqual(height, 512)
```

在 `tests/test_theme.py` 增加 `aurora_cyan`、`aurora_purple`、`aurora_emerald` 令牌断言，并在静态 UI 测试中要求 Logo 经过 `subsample` 处理。

- [ ] **Step 2: 运行失败测试**

运行 `PYTHONPATH=src python -m unittest tests.test_macos_distribution tests.test_theme -v`，预期 PNG 尺寸测试失败，因为当前 `app.png` 是 64×64。

- [ ] **Step 3: 生成资源并实现缩放**

使用 `sips -s format png packaging/icons/app.svg --out packaging/icons/app.png` 生成 1024×1024 PNG。更新 `packaging/icons/README.md` 说明 SVG 是源稿，PNG 用于运行时显示且必须保持至少 512×512，ICNS/ICO 继续用于平台打包。

在 `_build_header` 加载 PNG 后保留原图引用，按 `PhotoImage.width()` 计算缩小因子，把显示图缩小到约 36 像素后再交给 `ttk.Label`。缺少资源时保留文字回退。

在 `theme.py` 的两套调色板加入三种极光色令牌，更新玻璃表面和高光样式时只使用现有控件令牌，不改变 `teal` 的兼容值和输入控件可读性。

- [ ] **Step 4: 运行视觉和资源测试**

运行 `PYTHONPATH=src python -m unittest tests.test_macos_distribution tests.test_theme -v`，预期全部通过。

- [ ] **Step 5: 提交**

```bash
git add packaging/icons/app.png packaging/icons/README.md src/jsj_desktop/ui/main_window.py src/jsj_desktop/ui/theme.py tests/test_macos_distribution.py tests/test_theme.py
git commit -m "feat: use high resolution logo and aurora glass tokens"
```

## Task 5: 让顶部更新按钮进入更新面板并同步状态

**Files:**
- Modify: `src/jsj_desktop/ui/main_window.py`
- Modify: `src/jsj_desktop/ui/update_dialog.py`
- Test: `tests/test_update_banner.py`
- Test: `tests/test_update.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_update_banner.py` 修改更新结果测试，加入：

```python
from types import SimpleNamespace

    def test_banner_opens_update_dialog_without_browser_navigation(self):
        result = SimpleNamespace(ok=True, offline=False,
                                 update_available=True, tag="v2.0.0",
                                 latest_version="2.0.0")
        window = self._open_window(check_update_on_startup=False)
        with patch.object(window, "_show_update") as show:
            window._show_update_banner(result)
            banners = self._banners(window)
            self.assertEqual(len(banners), 1)
            self.assertEqual(banners[0].cget("text"), "更新")
            banners[0].invoke()
        show.assert_called_once_with()
        self.browser.assert_not_called()

    def test_banner_hides_when_result_is_current(self):
        window = self._open_window(check_update_on_startup=False)
        window._show_update_banner(SimpleNamespace(
            ok=True, offline=False, update_available=True, tag="v2.0.0",
            latest_version="2.0.0"))
        window._show_update_banner(SimpleNamespace(
            ok=True, offline=False, update_available=False, tag="v2.0.0",
            latest_version="2.0.0"))
        self.assertEqual(self._banners(window), [])
```

在 `tests/test_update.py` 增加 `CheckResult` 的同版本修订断言，确认 `latest_revision=1` 时 `can_update` 为真。

- [ ] **Step 2: 运行失败测试**

运行 `PYTHONPATH=src python -m unittest tests.test_update_banner tests.test_update -v`，预期顶部按钮仍然打开浏览器或无法识别同版本修订。

- [ ] **Step 3: 实现顶部按钮和面板回调**

修改 `_show_update_banner`。在结果无效、离线、无更新或 tag 与版本不一致时调用 `pack_forget()` 并返回。有效更新显示文本为 `更新`，command 绑定 `_show_update`，不再调用 `webbrowser.open_new_tab`。

让 `_show_update` 创建 `UpdateDialog(self, on_check=self._show_update_banner)`。`UpdateDialog` 的回调参数保持可选，`_on_checked` 每次处理结果后调用回调，让最新、失败和离线状态都能隐藏顶部按钮。更新面板继续沿用现有队列、进度条、SHA256、安装回滚和成功/失败提示。

- [ ] **Step 4: 运行更新聚焦测试**

运行 `PYTHONPATH=src python -m unittest tests.test_update_banner tests.test_update -v`，预期所有更新检查、按钮和安装器测试通过。

- [ ] **Step 5: 提交**

```bash
git add src/jsj_desktop/ui/main_window.py src/jsj_desktop/ui/update_dialog.py tests/test_update_banner.py tests/test_update.py
git commit -m "feat: connect update banner to manual updater"
```

## Task 6: 更新发布说明、版本清单和 CI 检查

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/CONFIGURATION.md`
- Modify: `docs/RELEASE.md`
- Modify: `docs/UI_PARITY.md`
- Modify: `docs/FEATURE_PARITY.md`
- Modify: `.github/workflows/release.yml`
- Modify: `tools/check_update_channel.py`
- Test: `tests/test_update.py`
- Test: `tests/test_macos_distribution.py`

- [ ] **Step 1: 写发布配置失败断言**

在 `ReleaseConfigTest` 增加 `release_revision` 必须存在于仓库清单、发布说明和发布工作流生成清单的断言。在 UI parity 测试中加入 `PanedWindow`、`profile_button_row` 和窗口过渡标记。

- [ ] **Step 2: 运行失败测试**

运行 `PYTHONPATH=src python -m unittest tests.test_update.ReleaseConfigTest tests.test_macos_distribution -v`，预期因发布说明和 CI 模板还没有修订号与新 UI 标记而失败。

- [ ] **Step 3: 更新文档和工作流**

在 `CHANGELOG.md` 的 2.0.0 顶部新增“本次替换发布”小节，明确列出滚动、可调分栏、按钮排版、高清 Logo、液态玻璃令牌、Windows 窗口切换合帧、同版本修订更新和验证边界，并保留上一代 2.0.0 的兼容性说明。

在 README、配置和发布文档中说明 `release_revision`、顶部更新按钮和手动确认流程。发布工作流生成的 `release-notes.md` 明确列出四平台包、手动更新状态和相对上一代版本的改动。`check_update_channel.py` 检查清单中的 `release_revision` 为非负整数，生成清单时沿用模板值。

- [ ] **Step 4: 运行发布配置测试**

运行 `PYTHONPATH=src python -m unittest tests.test_update.ReleaseConfigTest tests.test_macos_distribution -v`，预期通过。

- [ ] **Step 5: 提交**

```bash
git add CHANGELOG.md README.md docs/CONFIGURATION.md docs/RELEASE.md docs/UI_PARITY.md docs/FEATURE_PARITY.md .github/workflows/release.yml tools/check_update_channel.py tests/test_update.py tests/test_macos_distribution.py
git commit -m "docs: describe 2.0.0 replacement release"
```

## Task 7: 全量验证并覆盖 GitHub v2.0.0 发布

**Files:**
- Verify all files changed by Tasks 1–6

- [ ] **Step 1: 运行全量测试与静态检查**

依次运行：

```bash
PYTHONPATH=src python -m unittest discover -s tests -t . -v
PYTHONPATH=src python -m jsj_desktop --self-test
python3 tools/check_no_pii.py --strict
python3 tools/check_update_channel.py --offline
git diff --check
```

预期全量测试退出码为 0，更新通道显示“校验通过”，无 PII 扫描结果，差异检查无输出。若 GUI 测试因无显示器跳过，只记录跳过原因，不把跳过当成 Windows 实机验证。

- [ ] **Step 2: 检查发布版本和资产**

确认 `__version__`、`pyproject.toml`、`packaging/version_info.txt` 和 `update/latest.json` 仍为 `2.0.0`，`release_revision` 为 1。运行 `gh auth status`、`gh release view v2.0.0 --repo ghy065178-blip/JinFlow`，确认当前 release 可编辑且旧资产可被 `--clobber` 覆盖。

- [ ] **Step 3: 提交最终实现并推送源码**

```bash
git status --short
git log --oneline -8
git push origin codex/theme-contrast-fix
```

如果仓库默认分支需要同步，使用当前已验证提交更新远端默认分支，再触发已有 release 工作流。不得将测试临时文件、用户数据或构建缓存加入提交。

- [ ] **Step 4: 覆盖 v2.0.0 Release**

使用仓库已有工作流或等效 GitHub CLI 操作更新同名 tag 和 release，上传四平台新资产、`latest.json`、`SHA256SUMS.txt` 和升级助手，并使用 `--clobber` 覆盖旧资产。Release 说明必须包含“更新、新增、修改、兼容性、验证”栏目。

- [ ] **Step 5: 验证发布结果**

运行 `gh release view v2.0.0 --repo ghy065178-blip/JinFlow` 和 `gh run list --repo ghy065178-blip/JinFlow --limit 5`。确认四平台资产、`latest.json` 的 `release_revision=1`、SHA256 文件和更新说明都存在。报告 Windows 实机窗口切换是否在 Actions 或真实设备完成，不把静态测试描述成视觉实测。

## Self-review

- 规格中的滚动、可调分栏、档案按钮、Logo、视觉令牌、Windows 过渡、同版本修订、顶部更新按钮和发布覆盖各有对应任务。
- 每个生产改动前都有失败测试步骤。
- 计划不迁移 UI 技术栈，不修改表单业务和用户数据格式。
- 旧清单缺失 `release_revision` 时按 0 处理，向后兼容现有 2.0.0 安装包。
- 计划中没有保留未定义的 TODO/TBD 或“自行处理”的实现步骤。
