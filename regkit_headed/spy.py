# -*- coding: utf-8 -*-
"""API 流量间谍:在页面里记录命中 url_pattern 的 fetch/XHR 请求与响应。

用途:在自动化流程里读取 SPA 的内部 API 响应(如 auth/me、列表接口),
不用自己逆向协议。注入后响应进 window.__rhSpyLog,dump_spy() 打印。
"""
from .util import log

_SPY_JS_TEMPLATE = """
(function () {
  if (window.__rhSpy) return;
  window.__rhSpy = true;
  window.__rhSpyLog = [];
  function rec(entry) {
    try { window.__rhSpyLog.push(entry); if (window.__rhSpyLog.length > 80) window.__rhSpyLog.shift(); } catch (e) {}
  }
  var want = function (u) {
    return /__PATTERN__/.test(u) && !/analytics|collect|g\\/collect/.test(u);
  };
  var of = window.fetch;
  if (of) {
    window.fetch = function (input, init) {
      var url = typeof input === 'string' ? input : (input && input.url) || '';
      var reqBody = '';
      try { reqBody = init && init.body ? String(init.body).slice(0, 2000) : ''; } catch (e) {}
      return of.apply(this, arguments).then(function (res) {
        if (want(String(url))) {
          var text = '';
          try { text = res.clone().text(); } catch (e) {}
          text.then(function (t) {
            rec({ url: String(url).slice(0, 160), method: (init && init.method || 'GET'), status: res.status, req: reqBody, body: String(t).slice(0, 1500), t: Date.now() });
          });
        }
        return res;
      });
    };
  }
  var OX = window.XMLHttpRequest;
  if (OX) {
    window.XMLHttpRequest = function () {
      var x = new OX();
      try {
        x.addEventListener('loadend', function () {
          if (want(String(x.__url || x.responseURL || ''))) {
            var b = '';
            try { b = String(x.responseText || '').slice(0, 1500); } catch (e) {}
            rec({ url: String(x.__url || '').slice(0, 160), method: x.__method || 'GET', status: x.status, req: String(x.__body || '').slice(0, 2000), body: b, t: Date.now() });
          }
        });
      } catch (e) {}
      return x;
    };
    var op = OX.prototype.open, osend = OX.prototype.send;
    OX.prototype.open = function (m, u) { this.__method = m; this.__url = u; return op.apply(this, arguments); };
    OX.prototype.send = function (b) { this.__body = b || ''; return osend.apply(this, arguments); };
  }
})();
"""


def build_spy_js(url_pattern):
    """生成间谍 JS。url_pattern:JS 正则源码(不带斜杠),匹配要记录的 URL。

    例: r"clerk\\.example\\.com|console\\.example\\.com/api"
    注意:在 JS 正则里写一个反斜杠,Python 源码里要两个(\\\\)。
    """
    if not url_pattern:
        raise ValueError("url_pattern 不能为空")
    if "__PATTERN__" in url_pattern:
        raise ValueError("url_pattern 非法")
    return _SPY_JS_TEMPLATE.replace("__PATTERN__", url_pattern)


def _active(tab):
    if tab is not None:
        return tab
    from .browser import current_page
    return current_page()


def read_spy_log(tab=None):
    """读出 window.__rhSpyLog(到达序,最新在尾)。"""
    import json
    try:
        raw = _active(tab).run_js("JSON.stringify(window.__rhSpyLog || [])")
        return json.loads(raw) if isinstance(raw, str) else []
    except Exception:
        return []


def dump_spy(tab=None, tail=25):
    arr = read_spy_log(tab)
    log("===== API SPY LOG (%d entries) =====" % len(arr))
    for e in arr[-tail:]:
        log("  %s %s %s" % (e.get("method", "?"), e.get("status", ""), e.get("url", "")))
        if e.get("req"):
            log("    req: %s" % str(e.get("req"))[:300])
        if e.get("body") and e.get("status", 0) not in (200, 201):
            log("    body: %s" % str(e.get("body"))[:400])
