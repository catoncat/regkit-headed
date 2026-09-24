# -*- coding: utf-8 -*-
"""纯逻辑单测:不 import DrissionPage、不起浏览器、不调 cloud-mail。
运行: python3 -m unittest discover tests -v
"""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from regkit_headed.otp import default_extractor
from regkit_headed.spy import build_spy_js
from regkit_headed.browser import BG_ARGS, resolve_launch
from regkit_headed import turnstile


class TestOtpExtractor(unittest.TestCase):
    def test_subject_prefix_code(self):
        self.assertEqual(default_extractor("noreply@x.com", "939559 is your verification code"), "939559")

    def test_non_prefix_rejected(self):
        self.assertIsNone(default_extractor("noreply@x.com", "your code is 939559"))

    def test_empty(self):
        self.assertIsNone(default_extractor("", ""))
        self.assertIsNone(default_extractor("a@b.c", None))


class TestFetchOtpBody(unittest.TestCase):
    def test_extractor_receives_text_body(self):
        import json
        from unittest import mock
        from regkit_headed import otp
        payload = {"items": [{"sender": "no-reply@example.com", "subject": "Sign in",
                               "text_body": "Your code is 481516", "received_at": "2026-01-01T00:00:00Z"}]}
        fake = mock.Mock(stdout=json.dumps(payload))
        seen = []
        def extract(sender, subject, body):
            seen.append(body)
            return "481516" if "481516" in body else None
        with mock.patch.object(otp.subprocess, "run", return_value=fake):
            code, _, _ = otp.fetch_otp("a@example.com", timeout=2, extract=extract, poll=0)
        self.assertEqual(code, "481516")
        self.assertEqual(seen, ["Your code is 481516"])


class TestSpyJs(unittest.TestCase):
    def test_pattern_injected(self):
        js = build_spy_js(r"clerk\.example\.com|console\.example\.com")
        self.assertIn(r"clerk\.example\.com|console\.example\.com", js)
        self.assertIn("__rhSpyLog", js)
        self.assertNotIn("__PATTERN__", js)

    def test_empty_pattern_rejected(self):
        with self.assertRaises(ValueError):
            build_spy_js("")


class TestResolveLaunch(unittest.TestCase):
    def setUp(self):
        for k in ("RH_PROXY", "RH_PINV6", "RH_CHROME_FG"):
            os.environ.pop(k, None)

    def test_defaults(self):
        cfg = resolve_launch()
        self.assertEqual(cfg, {"proxy": None, "pin_v6": None, "foreground": False})

    def test_env_fallback(self):
        os.environ["RH_PROXY"] = "http://127.0.0.1:17951"
        os.environ["RH_CHROME_FG"] = "1"
        cfg = resolve_launch()
        self.assertEqual(cfg["proxy"], "http://127.0.0.1:17951")
        self.assertTrue(cfg["foreground"])

    def test_kwarg_beats_env(self):
        os.environ["RH_PROXY"] = "http://env:1"
        cfg = resolve_launch(proxy="http://kw:2", foreground=False)
        self.assertEqual(cfg["proxy"], "http://kw:2")
        self.assertFalse(cfg["foreground"])

    def test_bg_args_anti_throttle(self):
        joined = " ".join(BG_ARGS)
        self.assertIn("--disable-background-timer-throttling", joined)
        self.assertIn("--disable-backgrounding-occluded-windows", joined)
        self.assertIn("--disable-renderer-backgrounding", joined)


class TestTurnstileJs(unittest.TestCase):
    def test_patch_covers_screen_xy(self):
        self.assertIn("screenX", turnstile.TURNSTILE_PATCH_JS)
        self.assertIn("screenY", turnstile.TURNSTILE_PATCH_JS)
        self.assertIn("MouseEvent.prototype", turnstile.TURNSTILE_PATCH_JS)

    def test_token_readers(self):
        self.assertIn("cf-turnstile-response", turnstile.JS_READ_TOKEN)
        self.assertIn("cf-turnstile-response", turnstile.JS_CF_PRESENT)

    def test_min_token_len(self):
        self.assertGreaterEqual(turnstile.MIN_TOKEN_LEN, 80)


if __name__ == "__main__":
    unittest.main()
