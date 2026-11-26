# -*- coding: utf-8 -*-
import unittest
from datetime import datetime, timezone

from jsj_desktop.core.constants import CST, format_beijing_time, now_beijing


class BeijingTimeTest(unittest.TestCase):
    def test_shared_timezone_converts_utc_to_beijing(self):
        value = now_beijing(datetime(2026, 11, 26, 12, 0,
                                     tzinfo=timezone.utc))
        self.assertEqual(value.hour, 20)
        self.assertEqual(value.utcoffset().total_seconds(), 8 * 60 * 60)
        self.assertEqual(value.tzinfo, CST)

    def test_clock_format_is_seconds(self):
        value = datetime(2026, 11, 26, 20, 3, 4, tzinfo=CST)
        self.assertEqual(format_beijing_time(value), "20:03:04")


if __name__ == "__main__":
    unittest.main()
