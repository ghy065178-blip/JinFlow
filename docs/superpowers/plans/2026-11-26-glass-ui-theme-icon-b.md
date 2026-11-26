# 1.3.0 Glass UI, Theme, and Icon B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Jinshuju Registration Desktop 1.3.0 with scheme B app icons, a glass-style visual enhancement that preserves the 1.2.0 layout, three persisted theme modes, and a verified Beijing-time header clock.

**Architecture:** Keep `MainWindow`'s existing header, taskbar, status cards, left scroll area, terminal, menus, and dialogs. Centralize visual tokens and theme resolution in `ui/theme.py`, persist only the selected mode in `data/settings_store.py`, and make all existing UI layers reread the active tokens when a mode changes. Reuse the current header clock region and shared timezone constant instead of adding a new layout region.

**Tech Stack:** Python 3.11+ standard library, tkinter/ttk, `zoneinfo` with a UTC+8 fallback, SVG source plus platform icon assets, unittest, existing PyInstaller and release workflow.

---

### Task 1: Add failing tests for theme settings and Beijing time

**Files:**
- Create: `tests/test_theme.py`
- Modify: `tests/test_stores.py`
- Modify: `tests/test_ui_parity.py`
- Modify: `tests/test_smoke.py`

- [ ] **Step 1: Add a settings default test that expects the new mode**

Add this method to `tests/test_stores.py` inside `SettingsTest`.

```python
def test_theme_mode_defaults_to_system_and_round_trips(self):
    with tempfile.TemporaryDirectory() as tmp:
        store = Settings(Path(tmp) / "settings.json")
        self.assertEqual(store.load()["theme_mode"], "system")
        data = store.load()
        data["theme_mode"] = "light"
        store.save(data)
        self.assertEqual(store.load()["theme_mode"], "light")
```

- [ ] **Step 2: Add theme resolution and palette tests**

Create `tests/test_theme.py` with tests that import `resolve_mode`, `palette_for`, and `normalize_mode`.

```python
import unittest

from jsj_desktop.ui.theme import normalize_mode, palette_for, resolve_mode


class ThemeTest(unittest.TestCase):
    def test_normalize_mode_keeps_supported_values(self):
        self.assertEqual(normalize_mode("dark"), "dark")
        self.assertEqual(normalize_mode("light"), "light")
        self.assertEqual(normalize_mode("system"), "system")

    def test_normalize_mode_recovers_from_old_or_invalid_values(self):
        self.assertEqual(normalize_mode(""), "system")
        self.assertEqual(normalize_mode("sepia"), "system")

    def test_palette_for_contains_glass_tokens_and_semantic_colors(self):
        for mode in ("dark", "light"):
            palette = palette_for(mode)
            for key in ("bg", "surface", "surface2", "border", "highlight",
                        "shadow", "text", "muted", "teal", "green", "red"):
                self.assertIn(key, palette)
            self.assertEqual(palette["teal"], "#2dd4bf")
            self.assertNotEqual(palette["bg"], palette["surface"])

    def test_resolve_mode_uses_explicit_modes_without_system_probe(self):
        self.assertEqual(resolve_mode("dark", system_mode="light"), "dark")
        self.assertEqual(resolve_mode("light", system_mode="dark"), "light")
        self.assertEqual(resolve_mode("system", system_mode="dark"), "dark")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Add Beijing time tests before changing timezone code**

Add a new `tests/test_time.py`.

```python
import unittest
from datetime import datetime, timezone

from jsj_desktop.core.constants import CST, format_beijing_time, now_beijing


class BeijingTimeTest(unittest.TestCase):
    def test_shared_timezone_is_asia_shanghai_or_utc_plus_eight(self):
        self.assertEqual(now_beijing(datetime(2026, 11, 26, 12, 0,
                                              tzinfo=timezone.utc)),
                         datetime(2026, 11, 26, 20, 0, tzinfo=CST))

    def test_clock_format_is_seconds(self):
        value = datetime(2026, 11, 26, 20, 3, 4, tzinfo=CST)
        self.assertEqual(format_beijing_time(value), "20:03:04")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Extend static UI checks for the existing layout and theme control**

Add assertions to `tests/test_ui_parity.py` that `theme_mode`, `theme_buttons`, `clock_var`, `apply_theme`, and the existing layout markers remain in `main_window.py`. The assertions must continue to require `self.left_scroll` and `self.term_frame`, so the test fails if the redesign reintroduces a layout move.

- [ ] **Step 5: Run the new tests and confirm the expected RED state**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_theme tests.test_time tests.test_stores tests.test_ui_parity -v
```

Expected result is failure for missing `theme_mode`, theme helpers, and clock helpers. Fix test import or syntax errors before continuing.

### Task 2: Implement theme tokens and settings persistence

**Files:**
- Modify: `src/jsj_desktop/data/settings_store.py:11-18`
- Modify: `src/jsj_desktop/ui/theme.py:1-150`
- Test: `tests/test_theme.py`
- Test: `tests/test_stores.py`

- [ ] **Step 1: Add a backward-compatible settings default**

Add `"theme_mode": "system"` to `DEFAULTS`. Keep the existing merge behavior so old JSON files gain the field in memory without requiring migration.

- [ ] **Step 2: Add explicit palette definitions**

Keep the existing dark semantic colors and create a light palette that changes only background, surface, border, text, log, and input layers. Add `highlight`, `shadow`, `glass`, `glass_highlight`, and `log_bg` tokens to both palettes.

- [ ] **Step 3: Add minimal theme helpers**

Implement these functions in `ui/theme.py`.

```python
THEME_MODES = ("dark", "light", "system")


def normalize_mode(value):
    value = str(value or "").strip().lower()
    return value if value in THEME_MODES else "system"


def resolve_mode(mode, system_mode="light"):
    mode = normalize_mode(mode)
    return normalize_mode(system_mode) if mode == "system" else mode


def palette_for(mode):
    return dict(_PALETTES[resolve_mode(mode, system_mode="light")])
```

`apply(root, mode="system", system_mode="light")` must mutate the existing `PALETTE` dictionary in place, update `LEVEL_COLORS`, configure ttk styles, and return the resolved mode. In-place mutation preserves the imports used by `main_window.py`, `widgets.py`, and `update_dialog.py`.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_theme tests.test_stores -v
```

### Task 3: Implement system detection and real Beijing time

**Files:**
- Modify: `src/jsj_desktop/core/constants.py:1-16`
- Modify: `src/jsj_desktop/core/engine.py:16,109,296,333`
- Modify: `src/jsj_desktop/core/endpoint.py:14,139`
- Modify: `src/jsj_desktop/ui/main_window.py:31,577-628`
- Test: `tests/test_time.py`

- [ ] **Step 1: Add a shared timezone object with a safe fallback**

In `core/constants.py`, import `ZoneInfo` and define `CST` with `ZoneInfo("Asia/Shanghai")`. Catch `ZoneInfoNotFoundError` and use the existing fixed UTC+8 timezone. Add:

```python
def now_beijing(value=None):
    value = value or datetime.now(timezone.utc)
    return value.astimezone(CST)


def format_beijing_time(value=None):
    return now_beijing(value).strftime("%H:%M:%S")
```

Import `datetime` and `timezone` in the constants module as needed.

- [ ] **Step 2: Replace duplicate UI and engine clock calls**

Use `now_beijing()` and `format_beijing_time()` for the UI header, countdown calculations, manual-time logging, endpoint open-time conversion, and engine log timestamps. Preserve all existing strings and timing behavior.

- [ ] **Step 3: Add system appearance detection without third-party dependencies**

In `ui/theme.py`, add `detect_system_mode()`.

- On macOS, run `defaults read -g AppleInterfaceStyle` with a short timeout and return `dark` when the value is `Dark`.
- On Windows, read `AppsUseLightTheme` from `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize` and return `dark` when the value is `0`.
- On other platforms or any read failure, return `light`.

The helper is read-only and must never raise during startup.

- [ ] **Step 4: Run the time tests and existing engine tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_time tests.test_engine tests.test_endpoint -v
```

### Task 4: Add theme switching without changing main-window layout

**Files:**
- Modify: `src/jsj_desktop/ui/main_window.py:37-90,490-563,1450-1510`
- Modify: `src/jsj_desktop/ui/update_dialog.py:1-90`
- Modify: `src/jsj_desktop/ui/widgets.py:129-175`
- Test: `tests/test_ui_parity.py`

- [ ] **Step 1: Load the saved mode before building widgets**

Create `self.theme_mode` and `self.system_mode` from settings after the `TaskManager` exists. Call `apply_theme(self, self.theme_mode, self.system_mode)` before `_build_menu`, `_build_header`, `_build_taskbar`, `_build_cards`, `_build_main`, and `_build_overlays`.

- [ ] **Step 2: Add the existing-region theme control**

Inside the current “高级选项” section of `_build_settings`, add three mutually exclusive `ttk.Radiobutton` controls bound to `self.theme_mode_var`. Their values are `dark`, `light`, and `system`. The control stays inside the settings window and does not move header, taskbar, cards, left scroll, or terminal widgets.

- [ ] **Step 3: Apply and persist mode changes**

Implement `_on_theme_changed()` to normalize the selected value, save `theme_mode`, call `apply_theme`, refresh direct tkinter colors, and update the open settings, preview, toast, and update windows. Keep task state, logs, and data untouched.

- [ ] **Step 4: Refresh existing direct tkinter widgets by semantic color**

Add a small `refresh_tree(root, old_palette, new_palette)` helper in `ui/theme.py` that updates `background`, `foreground`, `insertbackground`, and `highlightbackground` only when the current value matches a known old token. Use it once after applying a mode so existing `tk.Label`, `tk.Frame`, `tk.Canvas`, `Text`, and `ScrolledText` controls change without reconstructing layout.

- [ ] **Step 5: Add periodic system-mode refresh**

In `_poll`, when `self.theme_mode == "system"`, check system appearance at most once every 2 seconds. Reapply the theme only if the resolved mode changed. Keep the existing 100 ms event queue and countdown behavior.

- [ ] **Step 6: Update update-dialog and widget colors**

Use the active `PALETTE` tokens for `UpdateDialog` text/log/progress surfaces and `LogView` tags. Do not change dialog sizes, component order, or buttons.

- [ ] **Step 7: Run focused UI tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_theme tests.test_ui_parity tests.test_scroll_input -v
```

### Task 5: Implement scheme B icon resources and packaging checks

**Files:**
- Create: `packaging/icons/app.svg`
- Create: `packaging/icons/app.icns`
- Create: `packaging/icons/app.ico`
- Modify: `packaging/icons/README.md`
- Modify: `tests/test_macos_distribution.py`

- [ ] **Step 1: Add the SVG source**

Create a 1024×1024 SVG with a deep-blue to indigo-to-rose rounded-square background, two offset translucent profile cards, and a white center node with two connector lines. Keep all text out of the artwork so the mark remains legible at small sizes.

- [ ] **Step 2: Generate platform assets from the source**

On macOS, create the multi-size `.icns` with `iconutil` and generate `.ico` with an available local image converter. If a converter is unavailable, keep the SVG source and use the repository's documented fallback until a converter is available. Do not add a runtime dependency.

- [ ] **Step 3: Extend packaging tests**

Assert that the icon source exists, the macOS build checks `packaging/icons/app.icns`, and the Windows build checks `packaging/icons/app.ico`. Keep missing icon behavior as a documented fallback for source-only builds.

- [ ] **Step 4: Run packaging-focused tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_macos_distribution tests.test_no_pii -v
```

### Task 6: Update 1.3.0 metadata and documentation

**Files:**
- Modify: `src/jsj_desktop/__init__.py`
- Modify: `pyproject.toml`
- Modify: `packaging/version_info.txt`
- Modify: `update/latest.json`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/CONFIGURATION.md`
- Modify: `docs/USER_GUIDE.md`
- Modify: `docs/UI_PARITY.md`
- Modify: `docs/RELEASE.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `tests/test_update.py`

- [ ] **Step 1: Set the application version to 1.3.0**

Update the runtime version, Python package version, Windows version resource, manifest latest version, tag, upgrade target, download base, and notes. Keep historical upgrade paths for 1.0.0–1.0.3 and state that their data format remains compatible with 1.3.0.

- [ ] **Step 2: Add 1.3.0 release notes**

Document scheme B icon assets, glass-style visual tokens, theme modes, system appearance behavior, and the Beijing-time refresh correction. Keep the existing limitation that the standard-library tkinter implementation uses a cross-platform glass simulation rather than native backdrop blur.

- [ ] **Step 3: Update user and configuration documentation**

Document `theme_mode` in `settings.json`, the settings control path, the three theme states, the header clock source and format, and the icon packaging paths.

- [ ] **Step 4: Update static version tests and run the update suite**

Adjust only assertions that intentionally name the current version or release notes. Run:

```bash
PYTHONPATH=src python -m unittest tests.test_update tests.test_smoke -v
```

### Task 7: Full verification and GitHub release

**Files:**
- Modify: all implementation and documentation files listed above
- Test: full `tests/` suite and release workflow checks

- [ ] **Step 1: Run the complete local test suite**

Run:

```bash
PYTHONPATH=src python -m unittest discover -s tests -t . -v
```

Record any local HTTP bind failure separately if the sandbox still blocks loopback servers. No UI or business-logic test failure may remain.

- [ ] **Step 2: Run repository self-checks**

Run:

```bash
PYTHONPATH=src python -m jsj_desktop --self-test
python tools/check_no_pii.py --strict
python tools/check_update_channel.py --offline
```

- [ ] **Step 3: Build the source package metadata and inspect the diff**

Run:

```bash
git diff --check
git status --short
```

Review that no personal data, downloaded archives, `.superpowers` content, or unrelated generated files are staged.

- [ ] **Step 4: Commit the implementation**

Use separate commits when practical, with the final implementation commit message:

```bash
git add src tests packaging update docs README.md CHANGELOG.md pyproject.toml .github
git commit -m "feat: release 1.3.0 glass UI and theme controls"
```

- [ ] **Step 5: Push the `1.3.0` source and tag**

After verifying GitHub authentication and the remote branch, push the source branch and create an annotated tag.

```bash
git push origin main
git tag -a v1.3.0 -m "1.3.0 glass UI, scheme B icon, and theme controls"
git push origin v1.3.0
```

- [ ] **Step 6: Verify the GitHub release**

Confirm the `v1.3.0` Actions run, release assets, manifest version, and release notes through the repository's Releases page. Report any missing platform artifact instead of claiming the release is complete.

## Self-review

- The spec's icon, glass, theme, clock, compatibility, and verification requirements each have a task.
- No task changes core submission semantics or moves the existing main-window regions.
- Theme mode names, palette helpers, settings keys, and clock helper names are consistent across tasks.
- No placeholder task remains. The only expected environment exception is the previously observed loopback HTTP bind restriction.
