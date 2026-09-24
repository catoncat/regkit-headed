# regkit-headed

Python primitives for automating pages that sit behind Cloudflare Turnstile or
similar browser checks, where plain HTTP replay and headless browsers are rejected.

It drives a real Chrome through [DrissionPage](https://github.com/g1879/DrissionPage),
launched in the background so it never steals focus, and adds:

- a CDP-injected patch applied to every document, including the Turnstile iframe
- a Turnstile wait / reset / checkbox loop that returns the token
- OTP polling through the [cloud-mail](https://github.com/catoncat/cloud-mail) CLI
- in-page capture of fetch/XHR responses, so an SPA's internal API can be read without reverse engineering

Companion to [regkit](https://github.com/catoncat/regkit): this package covers the
browser-driven part, and regkit takes the result from there (key pool, gateway,
usage ledger, watcher).

## Install

Requires macOS with Google Chrome (the background launcher uses `open -n -g`), Python >= 3.9.

```bash
git clone https://github.com/catoncat/regkit-headed.git
pip install -e ./regkit-headed        # into your project's venv
```

For `fetch_otp`, install and configure the `cloud-mail` CLI (see the cloud-mail README),
or pass `mail_cli=` pointing at any tool that answers
`<cli> messages --email <addr> --limit <n>` with `{ "items": [...] }`.

## Usage

Your project keeps its own page-flow script; this package supplies the steps.

```python
from regkit_headed import (
    start_browser, stop_browser, wait_turnstile,
    click_button_by_text, wait_url_contains, fetch_otp, shot, dump_spy,
)

browser, page = start_browser(
    proxy="http://127.0.0.1:8080",            # optional, per-instance only
    spy_pattern=r"console\.example\.com/api",  # optional: record matching API responses
)
try:
    page.get("https://auth.example.com/sign-in")
    # ... fill the form, click Continue ...
    wait_turnstile(40, "sign-in")             # token on pass, "" if no widget, raises on timeout
    code, _, _ = fetch_otp(email, timeout=120)
    # ... enter the code; read results with dump_spy() or page.listen ...
finally:
    stop_browser()
```

| Function | What it does |
|---|---|
| `start_browser(proxy, pin_v6, foreground, spy_pattern, extra_args)` | Real Chrome on its own port and temporary profile, started in the background with anti-throttling flags, patch injected. Env fallbacks: `RH_PROXY`, `RH_PINV6`, `RH_CHROME_FG` |
| `wait_turnstile(timeout, label)` | Waits for a token of at least 80 characters; resets the widget every 8 s; returns `""` when the page has no widget |
| `fetch_otp(email, extract=..., only_newer_than=...)` | Polls the mailbox; the default extractor takes a 6-digit code at the start of the subject. `extract(sender, subject, body)` replaces it |
| `click_button_by_text`, `wait_url_contains`, `shot` | Small page helpers |
| `build_spy_js`, `read_spy_log`, `dump_spy` | In-page fetch/XHR recorder |

Notes:

- Background is the default. `foreground=True` (or `RH_CHROME_FG=1`) is for debugging only.
- Proxies are set per browser instance; the system proxy is never touched.
- Do not call DrissionPage's `set_user_data_path`: `auto_port()` already gives each
  instance its own port and profile, and a fixed path breaks the connection.

## Tests

```bash
python3 -m unittest discover tests -v   # pure logic, no browser or DrissionPage needed
```

Browser paths are verified against a real Turnstile page: start the browser, open the
page, get a token from `wait_turnstile`, and stop without submitting anything.

## License

MIT
