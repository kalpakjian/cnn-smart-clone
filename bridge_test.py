#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測試 cloneBridge Web App 是否可用 (ping)。

用法:
    python bridge_test.py [url] [secret]

未給 url 時讀取 bridge_url.txt。會印出 HTTP 狀態與回應內容。
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backup_cnn_drive as b  # noqa: E402
URL_FILE = os.path.join(HERE, "bridge_url.txt")


def load_url():
    if len(sys.argv) > 1:
        return sys.argv[1].strip().lstrip("\ufeff")
    if os.path.exists(URL_FILE):
        with open(URL_FILE, "r", encoding="utf-8-sig") as fh:
            return fh.read().strip()
    return None


def call(url, params, timeout=300):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "cnn-clone-bridge/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode(errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")
    except Exception as exc:  # noqa: BLE001
        return -1, str(exc)


def main():
    url = load_url()
    if not url:
        print("找不到 Web App 網址 (bridge_url.txt 不存在)")
        return 1
    secret = sys.argv[2] if len(sys.argv) > 2 else b.bridge_secret()
    action = sys.argv[3] if len(sys.argv) > 3 else "ping"

    print("URL: %s" % url)
    print("action=%s" % action)
    status, body = call(url, {"action": action, "secret": secret})
    print("HTTP %s" % status)
    print("---- 回應 (前 1200 字) ----")
    print(body[:1200])
    if body.lstrip().startswith("{"):
        try:
            out = json.loads(body)
            if out.get("ok"):
                print("\nRESULT: BRIDGE_OK ✅")
                return 0
            print("\nRESULT: BRIDGE_ERROR ❌ %s" % out.get("error"))
            return 2
        except Exception:  # noqa: BLE001
            pass
    print("\nRESULT: NOT_JSON (可能未授權或部署設定未生效)")
    return 3


if __name__ == "__main__":
    sys.exit(main())
