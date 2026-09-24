# -*- coding: utf-8 -*-
"""真实 Chrome 启动器:后台不抢焦点 + 独立端口/profile + per-instance 代理 + CDP 补丁注入。

DrissionPage 只在 start_browser() 里惰性 import——本包纯逻辑(otp/spy/参数组装)
不装 DrissionPage 也能 import 和单测。

macOS 要点:
  - DrissionPage 4.1.x: 绝不 set_user_data_path,auto_port() 即可(独立端口+临时 profile);
  - 默认经 bin/chrome-bg.sh 用 open -n -g 后台拉起,前台 app 不被切换;
    想前台排查: start_browser(foreground=True) 或 env RH_CHROME_FG=1;
  - 后台窗口必须带 BG_ARGS 反节流/反遮挡参数,否则 Chrome 判 occluded 限速,
    Turnstile 会受影响。
"""
import os, time

from .util import log
from .turnstile import TURNSTILE_PATCH_JS
from .spy import build_spy_js

BG_ARGS = [
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-features=CalculateNativeWinOcclusion,NativeWindowOcclusion",
    "--window-size=900,700",
]

_CHROME_BG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "chrome-bg.sh")

_SESSION = {"browser": None, "page": None}


def current_browser():
    return _SESSION["browser"]


def current_page():
    return _SESSION["page"]


def resolve_launch(proxy=None, pin_v6=None, foreground=None):
    """参数/env 归一(纯函数,单测覆盖)。显式参数优先,env(RH_*)兜底。

    RH_PROXY   : per-instance 代理(http://user:pass@host:port 或 http://127.0.0.1:port)
    RH_PINV6   : --host-resolver-rules 值(把目标域钉到指定 IPv6)
    RH_CHROME_FG: 非空 = 前台启动(排查用)
    """
    return {
        "proxy": proxy if proxy is not None else (os.environ.get("RH_PROXY") or None),
        "pin_v6": pin_v6 if pin_v6 is not None else (os.environ.get("RH_PINV6") or None),
        "foreground": foreground if foreground is not None else bool(os.environ.get("RH_CHROME_FG")),
    }


def inject_patch(tab, spy_pattern=None):
    """给 tab 注入 Turnstile 指纹补丁(+ 可选 API 间谍),全 document 生效。"""
    try:
        tab.run_cdp("Page.enable")
    except Exception:
        pass
    ok = True
    sources = [TURNSTILE_PATCH_JS]
    if spy_pattern:
        sources.append(build_spy_js(spy_pattern))
    for src in sources:
        try:
            tab.run_cdp("Page.addScriptToEvaluateOnNewDocument", source=src, runImmediately=True)
        except Exception as exc:
            ok = False
            log("[!] 注入失败:", exc)
    return ok


def start_browser(proxy=None, pin_v6=None, foreground=None, spy_pattern=None,
                  extra_args=None, chrome_bg=None, retries=3):
    """起真实 Chrome 并注入补丁,返回 (browser, page)。

    spy_pattern: 传 JS 正则源码则同时注入 API 间谍(见 spy.build_spy_js)。
    """
    from DrissionPage import Chromium, ChromiumOptions  # 惰性:纯逻辑不依赖 DP

    cfg = resolve_launch(proxy, pin_v6, foreground)
    wrapper = os.path.abspath(chrome_bg or _CHROME_BG)
    for attempt in range(1, retries + 1):
        try:
            options = ChromiumOptions()
            options.auto_port()
            if cfg["proxy"]:
                options.set_proxy(cfg["proxy"])
                log("[*] 走代理:", cfg["proxy"])
            if cfg["pin_v6"]:
                options.set_argument("--host-resolver-rules", cfg["pin_v6"])
                log("[*] v6 钉死:", cfg["pin_v6"][:80])
            options.set_timeouts(base=1)
            for a in BG_ARGS + list(extra_args or []):
                options.set_argument(a)
            if not cfg["foreground"]:
                options.set_browser_path(wrapper)
                log("[*] 后台启动浏览器(browser_path -> chrome-bg.sh;RH_CHROME_FG=1 恢复前台)")
            browser = Chromium(options)
            tabs = browser.get_tabs()
            page = tabs[-1] if tabs else browser.new_tab()
            inject_patch(page, spy_pattern=spy_pattern)
            _SESSION["browser"] = browser
            _SESSION["page"] = page
            log("[*] 浏览器已启动 (patch injected)")
            return browser, page
        except Exception as exc:
            log("[!] 浏览器启动失败(第%d/%d次): %s" % (attempt, retries, exc))
            stop_browser()
            time.sleep(2)
    raise Exception("浏览器启动失败")


def stop_browser():
    cur = _SESSION["browser"]
    _SESSION["browser"] = None
    _SESSION["page"] = None
    if cur is None:
        return
    try:
        cur.quit(del_data=True)
    except BaseException:
        pass
