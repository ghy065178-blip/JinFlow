# -*- coding: utf-8 -*-
import unittest

from jsj_desktop.ui.theme import normalize_mode, palette_for, resolve_mode


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
