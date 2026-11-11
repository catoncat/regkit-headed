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


class TestCfsolveHeadless(unittest.TestCase):
    def setUp(self):
        for key in ("RH_CFSOLVE_BIN", "RH_CFSOLVE_PROFILE"):
            os.environ.pop(key, None)

    def test_resolve_defaults_and_env(self):
        self.assertEqual(turnstile.resolve_cfsolve(), {"binary": "challenge", "profile": None})
        os.environ["RH_CFSOLVE_BIN"] = "/opt/challenge"
        os.environ["RH_CFSOLVE_PROFILE"] = "/opt/safari.json"
        cfg = turnstile.resolve_cfsolve()
        self.assertEqual(cfg["binary"], "/opt/challenge")
        self.assertEqual(cfg["profile"], "/opt/safari.json")

    def test_kwarg_beats_env(self):
        os.environ["RH_CFSOLVE_BIN"] = "/env/challenge"
        os.environ["RH_CFSOLVE_PROFILE"] = "/env/p.json"
        cfg = turnstile.resolve_cfsolve(binary="/kw/challenge", profile="/kw/p.json")
        self.assertEqual(cfg, {"binary": "/kw/challenge", "profile": "/kw/p.json"})

    def test_argv_widget(self):
        argv = turnstile.build_cfsolve_argv(
            "https://auth.example/sign-up", "/tmp/out", "profiles/safari.json",
            sitekey="0x4AAA", proxy="http://127.0.0.1:8080",
            action="login", cdata="abc", blank_page=True, binary="/bin/challenge",
        )
        self.assertEqual(argv, [
            "/bin/challenge", "--page", "https://auth.example/sign-up", "/tmp/out",
            "--solve", "--fingerprint", "profiles/safari.json",
            "--sitekey", "0x4AAA", "--action", "login", "--cdata", "abc",
            "--blank-page", "--proxy", "http://127.0.0.1:8080",
        ])

    def test_argv_challenge_page_omits_sitekey(self):
        argv = turnstile.build_cfsolve_argv("https://example/", "/tmp/out", "p.json")
        self.assertNotIn("--sitekey", argv)
        self.assertNotIn("--blank-page", argv)
        self.assertIn("--solve", argv)

    def test_argv_rejects_widget_flags_without_sitekey(self):
        with self.assertRaises(ValueError):
            turnstile.build_cfsolve_argv("https://example/", "/tmp/out", "p.json", action="login")
        with self.assertRaises(ValueError):
            turnstile.build_cfsolve_argv("https://example/", "/tmp/out", "p.json", blank_page=True)
        with self.assertRaises(ValueError):
            turnstile.build_cfsolve_argv(
                "https://example/", "/tmp/out", "p.json", sitekey="k", proxy="ftp://h",
            )

    def test_parse_token_and_clearance(self):
        token = turnstile.parse_cfsolve_stdout("noise\n0.token-value\n")
        self.assertEqual(token["token"], "0.token-value")
        self.assertEqual(token["cfClearance"], "")
        cleared = turnstile.parse_cfsolve_stdout("cf_clearance=abc.def")
        self.assertEqual(cleared, {"token": "", "cfClearance": "abc.def", "userAgent": ""})
        with self.assertRaises(turnstile.CfsolveError):
            turnstile.parse_cfsolve_stdout("  \n")
        with self.assertRaises(turnstile.CfsolveError):
            turnstile.parse_cfsolve_stdout("cf_clearance=")

    def test_user_agent_from_profile(self):
        import tempfile
        path = tempfile.mktemp(suffix=".json")
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"transport": {"headers": {"User-Agent": "Safari/26"}}}')
            self.assertEqual(turnstile.user_agent_from_profile(path), "Safari/26")
        finally:
            os.remove(path)

    def _profile(self, directory):
        path = os.path.join(directory, "profile.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"transport": {"headers": {"User-Agent": "TestUA/1"}}}')
        return path

    def test_solve_returns_token_and_removes_workdir(self):
        import tempfile
        from unittest import mock
        root = tempfile.mkdtemp(prefix="rh-cfsolve-test-")
        profile = self._profile(root)
        work = os.path.join(root, "work")
        os.mkdir(work)
        fake = mock.Mock(returncode=0, stdout="token-from-cli\n", stderr="progress\n")
        try:
            with mock.patch.object(turnstile.tempfile, "mkdtemp", return_value=work), \
                 mock.patch.object(turnstile.subprocess, "run", return_value=fake) as run:
                got = turnstile.solve_turnstile_headless(
                    "https://auth.example/sign-up", "0x4AAA", "socks5h://127.0.0.1:1080",
                    profile=profile, binary="/bin/challenge",
                )
            argv = run.call_args[0][0]
            self.assertEqual(argv[0], "/bin/challenge")
            self.assertIn("--sitekey", argv)
            self.assertIn("socks5h://127.0.0.1:1080", argv)
            self.assertEqual(got, {
                "token": "token-from-cli", "cfClearance": "", "userAgent": "TestUA/1",
            })
            self.assertFalse(os.path.exists(work))
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)

    def test_solve_clearance_and_keeps_caller_dir(self):
        import tempfile
        from unittest import mock
        root = tempfile.mkdtemp(prefix="rh-cfsolve-test-")
        profile = self._profile(root)
        work = os.path.join(root, "keep")
        os.mkdir(work)
        fake = mock.Mock(returncode=0, stdout="cf_clearance=cookie-value\n", stderr="")
        try:
            with mock.patch.object(turnstile.subprocess, "run", return_value=fake):
                got = turnstile.solve_turnstile_headless(
                    "https://example/", profile=profile, out_dir=work,
                )
            self.assertEqual(got["cfClearance"], "cookie-value")
            self.assertEqual(got["token"], "")
            self.assertTrue(os.path.isdir(work))
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)

    def test_solve_failure_modes(self):
        import tempfile
        from unittest import mock
        root = tempfile.mkdtemp(prefix="rh-cfsolve-test-")
        profile = self._profile(root)
        try:
            with mock.patch.object(turnstile.subprocess, "run") as run:
                with self.assertRaises(turnstile.CfsolveError):
                    turnstile.solve_turnstile_headless("https://example/")
                run.assert_not_called()
            with self.assertRaises(turnstile.CfsolveError):
                turnstile.solve_turnstile_headless("https://example/", profile=os.path.join(root, "missing.json"))
            with mock.patch.object(turnstile.subprocess, "run", side_effect=FileNotFoundError(2, "challenge")):
                with self.assertRaises(turnstile.CfsolveError) as missing:
                    turnstile.solve_turnstile_headless("https://example/", profile=profile, binary="/no/such")
            self.assertIn("RH_CFSOLVE_BIN", str(missing.exception))
            failed = mock.Mock(returncode=2, stdout="", stderr="Error: Rejected")
            with mock.patch.object(turnstile.subprocess, "run", return_value=failed):
                with self.assertRaises(turnstile.CfsolveError) as rejected:
                    turnstile.solve_turnstile_headless("https://example/", profile=profile, out_dir=root)
            self.assertIn("Rejected", str(rejected.exception))
            with mock.patch.object(
                turnstile.subprocess, "run",
                side_effect=turnstile.subprocess.TimeoutExpired(cmd="challenge", timeout=1),
            ):
                with self.assertRaises(turnstile.CfsolveError) as timed:
                    turnstile.solve_turnstile_headless("https://example/", profile=profile, timeout=1, out_dir=root)
            self.assertIn("超时", str(timed.exception))
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
