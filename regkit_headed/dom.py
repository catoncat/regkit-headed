# -*- coding: utf-8 -*-
"""页面 DOM 交互小工具。"""
import time

from .util import log


def _active(tab):
    if tab is not None:
        return tab
    from .browser import current_page
    return current_page()


def click_button_by_text(tab, texts, timeout=6):
    """按可见文本匹配并点击按钮,返回 (clicked, 见过的按钮文本摘要)。"""
    deadline = time.time() + timeout
    seen = set()
    while time.time() < deadline:
        try:
            btns = tab.eles("tag:button", timeout=2)
        except Exception:
            btns = []
        for b in btns:
            try:
                t = (b.text or "").strip()
            except Exception:
                continue
            if t and t not in seen:
                seen.add(t[:40])
                for kw in texts:
                    if kw in t:
                        try:
                            b.click()
                            return True, t
                        except Exception as exc:
                            log("[!] 点击按钮失败 %r: %s" % (t, exc))
        time.sleep(1)
    return False, (", ".join(list(seen)[:8]) if seen else "(no buttons)")


def wait_url_contains(needle, timeout=30, tab=None):
    active = _active(tab)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if needle in (active.url or ""):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def shot(name, tab=None, dir="/tmp", prefix="headed"):
    """截图留证,返回路径(失败返回 None,不抛)。"""
    try:
        path = "%s/%s_%s.png" % (dir, prefix, name)
        _active(tab).get_screenshot(path=path, full_page=False)
        log("[shot] " + path)
        return path
    except Exception as exc:
        log("[!] screenshot 失败:", exc)
        return None
