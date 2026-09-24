# -*- coding: utf-8 -*-
"""日志与杂项(纯函数/无副作用,不依赖 DrissionPage)。"""
import time


def log(*a):
    print("[" + time.strftime("%H:%M:%S") + "]", *a, flush=True)
