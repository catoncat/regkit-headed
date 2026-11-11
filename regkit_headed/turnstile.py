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
import json, os, shutil, subprocess, tempfile, time
from urllib.parse import urlsplit

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


# --- 纯协议无头求解(cfsolve 的 `challenge` CLI)。不起浏览器。 ---
#
# 上游二进制是 `cargo build --release --bin challenge`。默认运行的
# `cfsolve` 只是离线反混淆器,不是求解器。成功时 stdout 一行:
#   token            内嵌组件
#   cf_clearance=…   整页盾
# 进度在 stderr。输出目录必须是空的或尚不存在;本函数自建临时目录并在结束时删掉。
# User-Agent 不在 stdout 里,从 profile 的 transport.headers 读出,供后续业务请求对齐。

_PROXY_SCHEMES = ("http", "https", "socks5", "socks5h")


class CfsolveError(Exception):
    """cfsolve 二进制缺失、超时、非零退出或没有可用输出。"""


def resolve_cfsolve(binary=None, profile=None):
    """参数/env 归一(纯函数)。显式参数优先,env 兜底。

    RH_CFSOLVE_BIN     : `challenge` 二进制路径;缺省时按 PATH 上的 `challenge`
    RH_CFSOLVE_PROFILE : 指纹 profile JSON(如 profiles/safari-26-ios.json)
    """
    return {
        "binary": binary if binary is not None else (os.environ.get("RH_CFSOLVE_BIN") or "challenge"),
        "profile": profile if profile is not None else (os.environ.get("RH_CFSOLVE_PROFILE") or None),
    }


def user_agent_from_profile(path):
    """读 profile 里的 User-Agent。缺这个头返回 ""。文件打不开或不是 JSON 则抛给调用方。"""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    headers = (data.get("transport") or {}).get("headers") or {}
    for key, value in headers.items():
        if str(key).lower() == "user-agent" and value:
            return str(value)
    return ""


def _check_proxy(proxy):
    if not proxy:
        return
    parts = urlsplit(proxy)
    if parts.scheme not in _PROXY_SCHEMES or not parts.hostname:
        raise ValueError("proxy 只接受 http/https/socks5/socks5h 且必须带 host: %r" % (proxy,))


def build_cfsolve_argv(page_url, out_dir, profile, sitekey=None, proxy=None,
                       action=None, cdata=None, blank_page=False, binary="challenge"):
    """组装 `challenge` 的 argv(纯函数,不起进程)。

    有 sitekey 时指定组件;没有则 `--solve` 解页面上第一个组件,或清掉整页盾。
    `--blank-page` 只在拿不到页面 HTML、只有 sitekey 时打开。
    """
    if not page_url:
        raise ValueError("page_url 不能为空")
    if not profile:
        raise ValueError("fingerprint profile 不能为空")
    if not out_dir:
        raise ValueError("out_dir 不能为空")
    if not binary:
        raise ValueError("binary 不能为空")
    if (action or cdata or blank_page) and not sitekey:
        raise ValueError("action、cdata、blank_page 都要求 sitekey")
    _check_proxy(proxy)
    argv = [binary, "--page", page_url, out_dir, "--solve", "--fingerprint", profile]
    if sitekey:
        argv.extend(["--sitekey", sitekey])
    if action:
        argv.extend(["--action", action])
    if cdata:
        argv.extend(["--cdata", cdata])
    if blank_page:
        argv.append("--blank-page")
    if proxy:
        argv.extend(["--proxy", proxy])
    return argv


def parse_cfsolve_stdout(stdout):
    """解析求解器 stdout 的最后一行非空输出。进度在 stderr,不进这里。"""
    line = ""
    for raw in (stdout or "").splitlines():
        if raw.strip():
            line = raw.strip()
    if not line:
        raise CfsolveError("cfsolve 没有输出 token")
    prefix = "cf_clearance="
    if line.startswith(prefix):
        value = line[len(prefix):]
        if not value:
            raise CfsolveError("cfsolve 输出了空的 cf_clearance")
        return {"token": "", "cfClearance": value, "userAgent": ""}
    return {"token": line, "cfClearance": "", "userAgent": ""}


def solve_turnstile_headless(page_url, sitekey=None, proxy=None, *,
                              action=None, cdata=None, blank_page=False,
                              timeout=120, binary=None, profile=None, out_dir=None):
    """调 `challenge --solve` 拿 Turnstile token 或 cf_clearance。

    返回 {"token", "cfClearance", "userAgent"};没拿到的那一项是空字符串。
    代理不会隐式继承 RH_PROXY:传给求解器的出口必须和后续业务请求是同一个,
    由调用方显式传入。out_dir 缺省则用临时目录,结束即删;传入则交给调用方保留现场。
    """
    cfg = resolve_cfsolve(binary, profile)
    if not cfg["profile"]:
        raise CfsolveError("未配置 fingerprint profile;设置 RH_CFSOLVE_PROFILE 或传入 profile=")
    if not os.path.isfile(cfg["profile"]):
        raise CfsolveError("fingerprint profile 不存在: %s" % cfg["profile"])
    try:
        user_agent = user_agent_from_profile(cfg["profile"])
    except (OSError, json.JSONDecodeError) as exc:
        raise CfsolveError("无法读取 profile %s: %s" % (cfg["profile"], exc))
    owned = out_dir is None
    directory = out_dir or tempfile.mkdtemp(prefix="rh-cfsolve-")
    try:
        argv = build_cfsolve_argv(
            page_url, directory, cfg["profile"],
            sitekey=sitekey or None, proxy=proxy, action=action, cdata=cdata,
            blank_page=blank_page, binary=cfg["binary"],
        )
        log("[cfsolve] 求解 %s sitekey=%s" % (page_url, "yes" if sitekey else "no"))
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, errors="replace", timeout=timeout,
            )
        except FileNotFoundError:
            raise CfsolveError("找不到 cfsolve 二进制 %s;设置 RH_CFSOLVE_BIN" % cfg["binary"])
        except subprocess.TimeoutExpired:
            raise CfsolveError("cfsolve 超时(%ds)" % timeout)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[-800:]
            raise CfsolveError("cfsolve 退出 %s: %s" % (proc.returncode, tail))
        parsed = parse_cfsolve_stdout(proc.stdout)
        parsed["userAgent"] = user_agent
        kind = "cf_clearance" if parsed["cfClearance"] else "token"
        log("[cfsolve] 得到 %s 长度=%d" % (kind, len(parsed["cfClearance"] or parsed["token"])))
        return parsed
    finally:
        if owned:
            shutil.rmtree(directory, ignore_errors=True)
