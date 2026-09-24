# -*- coding: utf-8 -*-
"""regkit-headed:真实 Chrome 自动化原语(regkit 的兄弟包)。

面向有 Cloudflare Turnstile 等浏览器防护的页面:后台启动真实 Chrome(不抢焦点)+
CDP 指纹补丁 + Turnstile 通过循环 + cloud-mail OTP 胶水 + 页面内 API 记录。

调用方只写自己的页面流程脚本,用这里的原语拼装;拿到的结果交给 regkit 的池/网关。
"""
from .util import log
from .browser import (
    BG_ARGS,
    start_browser,
    stop_browser,
    inject_patch,
    resolve_launch,
    current_browser,
    current_page,
)
from .turnstile import (
    MIN_TOKEN_LEN,
    TURNSTILE_PATCH_JS,
    wait_turnstile,
    turnstile_state,
    read_token,
    click_turnstile_checkbox,
)
from .otp import fetch_otp, default_extractor
from .dom import click_button_by_text, wait_url_contains, shot
from .spy import build_spy_js, read_spy_log, dump_spy

__version__ = "0.1.0"
