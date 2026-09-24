#!/bin/bash
# chrome-bg.sh -- 后台启动 Chrome(不抢焦点、不弹到前台)
# regkit_headed.browser 默认把 DrissionPage 的浏览器路径指到这里
# (想前台排查: start_browser(foreground=True) 或 RH_CHROME_FG=1)。
# DrissionPage 会把 --remote-debugging-port/--user-data-dir 等参数原样传过来,
# 这里用 open -n -g 转发:-n 强制新实例(独立 profile),-g 后台启动不激活。
# 前台 app 不被切换,页面 visibilityState 保持 visible,Turnstile 不受影响。
exec open -n -g -a "Google Chrome" --args "$@"
