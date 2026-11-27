# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from jsj_desktop.ui.main_window import MainWindow
from jsj_desktop.ui.theme import (LEVEL_COLORS, apply, normalize_mode, palette_for,
                                  resolve_mode)


def _luminance(color):
    rgb = [value / 255 for value in bytes.fromhex(color[1:])]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
              for v in rgb]
    return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


class ThemeTest(unittest.TestCase):
    def test_normalize_mode_keeps_supported_values(self):
        self.assertEqual(normalize_mode("dark"), "dark")
        self.assertEqual(normalize_mode("light"), "light")
        self.assertEqual(normalize_mode("system"), "system")

    def test_normalize_mode_recovers_from_invalid_values(self):
        self.assertEqual(normalize_mode(""), "system")
        self.assertEqual(normalize_mode("sepia"), "system")

    def test_palette_for_contains_glass_tokens_and_semantic_colors(self):
        for mode in ("dark", "light"):
            palette = palette_for(mode)
            for key in ("bg", "surface", "surface2", "border", "highlight",
                        "shadow", "text", "muted", "teal", "green", "red",
                        "aurora_cyan", "aurora_purple", "aurora_emerald"):
                self.assertIn(key, palette)
            self.assertEqual(palette["teal"], "#2dd4bf")
            self.assertNotEqual(palette["bg"], palette["surface"])

    def test_resolve_mode_uses_explicit_modes_without_system_probe(self):
        self.assertEqual(resolve_mode("dark", system_mode="light"), "dark")
        self.assertEqual(resolve_mode("light", system_mode="dark"), "light")
        self.assertEqual(resolve_mode("system", system_mode="dark"), "dark")

    def test_theme_styles_keep_control_states_readable(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(root.destroy)
        root.withdraw()
        style = ttk.Style(root)
        for mode in ("light", "dark"):
            with self.subTest(mode=mode):
                apply(root, mode, system_mode="light")
                palette = palette_for(mode)
                cases = ((("readonly",), palette["input"]),
                         (("readonly", "focus"), palette["highlight"]))
                for state, background in cases:
                    self.assertEqual(
                        style.lookup("TCombobox", "fieldbackground", state), background)
                    self.assertEqual(
                        style.lookup("TCombobox", "foreground", state), palette["text"])
                for state in (("readonly", "focus"), ("readonly", "!focus")):
                    self.assertEqual(
                        style.lookup("TCombobox", "selectbackground", state),
                        palette["surface2"])
                    self.assertEqual(
                        style.lookup("TCombobox", "selectforeground", state),
                        palette["text"])
                self.assertEqual(
                    style.lookup("Theme.TRadiobutton", "indicatorforeground", ("selected",)),
                    palette["text"])
                self.assertEqual(
                    style.lookup("Theme.TRadiobutton", "indicatorbackground", ("pressed", "selected")),
                    palette["highlight"])
                for foreground, background in ((palette["dim"], palette["glass"]),
                                                (palette["muted"], palette["surface2"]),
                                                (palette["amber"], palette["warnbox"]),
                                                (palette["log_ts"], palette["log_bg"]),
                                                *[(color, palette["log_bg"])
                                                  for color in LEVEL_COLORS.values()]):
                    with self.subTest(foreground=foreground, background=background):
                        dark, light = sorted(map(_luminance, (foreground, background)))
                        self.assertGreaterEqual((light + 0.05) / (dark + 0.05), 4.5)

    def test_header_and_settings_share_theme_selection_without_rebuilding_ui(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {"JSJ_DATA_DIR": directory}):
            Path(directory, "settings.json").write_text(
                '{"theme_mode":"system","check_update_on_startup":false}',
                encoding="utf-8")
            try:
                window = MainWindow(data_dir=Path(directory))
            except tk.TclError as exc:
                if "display" not in str(exc):
                    raise
                self.skipTest(str(exc))
            try:
                window.withdraw()
                self.assertTrue(hasattr(window, "header_theme_buttons"),
                                "顶栏缺少三态主题控件")
                self.assertIsNotNone(window._brand_icon)
                self.assertIn(window._brand_icon.width(), (48, 72, 96))
                header = dict(window.header_theme_widgets)
                settings = {button.cget("value"): button for button in
                            window.theme_buttons.winfo_children()}
                self.assertEqual(set(header), {"dark", "system", "light"})
                self.assertEqual(header["system"].cget("style"),
                                 "SegmentActive.TButton")
                window.link_var.set("EXAMPLE")
                window.log_view.append("08:00:00", "info", "主题测试")
                for buttons, mode in ((header, "dark"), (settings, "light"),
                                      (header, "system")):
                    with self.subTest(mode=mode):
                        buttons[mode].invoke()
                        self.assertEqual(header[mode].cget("style"),
                                         "SegmentActive.TButton")
                        self.assertTrue(settings[mode].instate(("selected",)))
                        self.assertEqual(window.manager.settings.load()["theme_mode"], mode)
                        self.assertEqual(window.link_var.get(), "EXAMPLE")
                        self.assertIn("主题测试", window.log_view.text())
                self.assertIs(window.left_scroll.master, window.term_frame.master)
            finally:
                window.destroy()


if __name__ == "__main__":
    unittest.main()
