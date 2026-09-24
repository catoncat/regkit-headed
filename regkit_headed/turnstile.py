# -*- coding: utf-8 -*-
"""Cloudflare Turnstile 通过机械。

核心事实(改之前先读):
  - Turnstile 用点击事件的屏幕绝对坐标做真人判定;automation 下
    MouseEvent.screenX==0 是明显机器人特征。CDP
    Page.addScriptToEvaluateOnNewDocument 注入补丁(全 document 生效,
    含 challenges.cloudflare.com 的 iframe)是已验证的解。
  - 通过判据: input[name=cf-turnstile-response] 的 token >= MIN_TOKEN_LEN 字符。
  - 卡住时 turnstile.reset() 二次复用;组件未渲染(页面没挂 Turnstile)直接放行。
"""
import json, time

from .util import log

MIN_TOKEN_LEN = 80

TURNSTILE_PATCH_JS = """
(function () {
  function getRandomInt(min, max) { return Math.floor(Math.random() * (max - min + 1)) + min; }
  var sx = getRandomInt(800, 1200);
  var sy = getRandomInt(400, 600);
  try {
    Object.defineProperty(MouseEvent.prototype, 'screenX', { get: function () { return sx; } });
    Object.defineProperty(MouseEvent.prototype, 'screenY', { get: function () { return sy; } });
  } catch (e) {}
})();
"""

JS_READ_TOKEN = """
try {
  var byInput = String((document.querySelector('input[name="cf-turnstile-response"]') || {}).value || '').trim();
  if (byInput) return byInput;
  if (window.turnstile && typeof turnstile.getResponse === 'function') return String(turnstile.getResponse() || '').trim();
  return '';
} catch (e) { return ''; }
"""

JS_CF_PRESENT = """
try {
  var cfInput = document.querySelector('input[name="cf-turnstile-response"]');
  var present = !!cfInput || !!document.querySelector('iframe[src*="turnstile"], iframe[src*="challenges.cloudflare.com"], div.cf-turnstile, [data-sitekey], script[src*="turnstile"]');
  var token = String((cfInput && cfInput.value) || '').trim();
  return JSON.stringify({ present: present, tokenLen: token.length });
} catch (e) { return JSON.stringify({ present: false, tokenLen: 0 }); }
"""


def _active(tab):
    if tab is not None:
        return tab
    from .browser import current_page
    return current_page()


def read_token(tab=None):
    try:
        return str(_active(tab).run_js(JS_READ_TOKEN) or "").strip()
    except Exception:
        return ""


def turnstile_state(tab=None):
    """返回 (present, token_len)。读不透按 (False, 0) 放行——不存在的组件不当失败。"""
    try:
        raw = _active(tab).run_js(JS_CF_PRESENT)
        data = json.loads(raw) if isinstance(raw, str) else {}
        return bool(data.get("present")), int(data.get("tokenLen") or 0)
    except Exception:
        return False, 0


def click_turnstile_checkbox(tab=None):
    """穿透 shadow DOM 点交互复选框;找不到则退化为点击 turnstile 相关节点。"""
    active = _active(tab)
    clicked = False
    try:
        challenge_input = active.ele("@name=cf-turnstile-response", timeout=2)
    except Exception:
        challenge_input = None
    if challenge_input:
        try:
            wrapper = challenge_input.parent()
            iframe = wrapper.shadow_root.ele("tag:iframe", timeout=2) if wrapper.shadow_root else None
            if iframe:
                try:
                    iframe.run_js("""
function g(min,max){return Math.floor(Math.random()*(max-min+1))+min;}
var sx = g(800,1200), sy = g(400,700);
try { Object.defineProperty(MouseEvent.prototype,'screenX',{value:sx}); } catch(e){}
try { Object.defineProperty(MouseEvent.prototype,'screenY',{value:sy}); } catch(e){}
""")
                except Exception:
                    pass
                try:
                    body_shadow = iframe.ele("tag:body", timeout=2).shadow_root
                    checkbox = body_shadow.ele("tag:input", timeout=2)
                    if checkbox:
                        checkbox.click()
                        clicked = True
                except Exception:
                    pass
        except Exception:
            pass
    if not clicked:
        try:
            active.run_js("""
var nodes = Array.from(document.querySelectorAll('div, span, iframe')).filter(function (n) {
  var meta = String((n.className || '') + ' ' + (n.id || '') + ' ' + ((n.getAttribute && n.getAttribute('src')) || ''));
  return meta.toLowerCase().indexOf('turnstile') !== -1;
});
if (nodes.length && typeof nodes[0].click === 'function') nodes[0].click();
""")
        except Exception:
            pass
    return clicked


def wait_turnstile(timeout=60, label="", tab=None):
    """等到 Turnstile token 达标;组件未渲染返回 ""(放行);超时抛异常。"""
    active = _active(tab)
    deadline = time.time() + timeout
    last_click = 0.0
    last_report = 0.0
    tlen = 0
    while time.time() < deadline:
        present, tlen = turnstile_state(active)
        if not present:
            log("[turnstile] %s: 页面未渲染 Turnstile(跳过)" % label)
            return ""
        tok = read_token(active)
        if len(tok) >= MIN_TOKEN_LEN:
            log("[turnstile] %s: 通过, token 长度=%d" % (label, len(tok)))
            return tok
        now = time.time()
        if now - last_report >= 8:
            last_report = now
            log("[turnstile] %s: 等待中... token 长度=%d" % (label, tlen))
        if now - last_click >= 8:
            last_click = now
            try:
                active.run_js("try { window.turnstile && turnstile.reset && turnstile.reset(); } catch(e){}")
            except Exception:
                pass
        click_turnstile_checkbox(active)
        time.sleep(1)
    raise Exception("Turnstile 超时(%ds): %s token 长度=%d" % (timeout, label, tlen))
