# -*- coding: utf-8 -*-
"""cloud-mail OTP 胶水:轮询收件箱取验证码。零依赖(只调 cloud-mail CLI)。

在 launchd 等极简环境里运行时,PATH 必须包含 cloud-mail 所在目录。
"""
import json, re, subprocess, time

from .util import log


def default_extractor(sender, subject, body=""):
    """默认取码器:subject 开头的 6 位数字(cloud-mail 验证邮件常见格式,
    形如 "939559 is your verification code")。命中返回 code,否则 None。"""
    m = re.search(r"^(\d{6})\b", (subject or "").strip())
    return m.group(1) if m else None


def fetch_otp(email, timeout=90, extract=None, poll=3, mail_cli="cloud-mail",
              only_newer_than=None):
    """轮询 cloud-mail 取验证码,返回 (code, sender, subject)。

    extract(sender, subject, body) -> code|None;缺省 default_extractor。
    only_newer_than: 只认 received_at 晚于该值的邮件(ISO 字符串比较)。
    """
    extract = extract or default_extractor
    deadline = time.time() + timeout
    last_report = 0.0
    while time.time() < deadline:
        try:
            out = subprocess.run(
                [mail_cli, "messages", "--email", email, "--limit", "8"],
                capture_output=True, text=True, timeout=20,
            )
            data = json.loads(out.stdout)
        except Exception as exc:
            if time.time() - last_report > 15:
                last_report = time.time()
                log("[mail] 读取失败: %s" % exc)
            time.sleep(poll)
            continue
        items = data.get("items") or []
        items.sort(key=lambda x: x.get("received_at") or "", reverse=True)
        for it in items:
            if only_newer_than and (it.get("received_at") or "") <= only_newer_than:
                continue
            body = it.get("text_body") or it.get("body") or it.get("html_body") or ""
            code = extract(it.get("sender") or "", it.get("subject") or "", body)
            if code:
                log("[mail] 收到 OTP %s 来自 %s (subject: %s)" % (code, it.get("sender"), it.get("subject")))
                return code, it.get("sender") or "", it.get("subject") or ""
        now = time.time()
        if now - last_report > 15:
            last_report = now
            log("[mail] 等待验证码邮件... (%ds)" % int(now - (deadline - timeout)))
        time.sleep(poll)
    raise Exception("OTP 邮件超时(%ds): %s" % (timeout, email))
