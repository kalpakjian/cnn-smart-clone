#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""透過 Apps Script API (scripts.run) 直接執行雲端 Apps Script 函式。

這是「讓 Python 端能真正觸發雲端複製」最乾淨的做法: 不需要公開 Web App 端點。

用法:
    python gs_run.py startSmartCloneCNN          # dev mode 執行
    python gs_run.py startSmartCloneCNN --nondev # 用 API 可執行部署

前置需求 (只需做一次):
    到 https://script.google.com/home/usersettings 開啟「Google Apps Script API」。
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backup_cnn_drive as b  # noqa: E402
import gs_files  # noqa: E402


def run_function(function_name, dev_mode=True, params=None):
    url = ("https://script.googleapis.com/v1/scripts/%s:run"
           % urllib.parse.quote(gs_files.SCRIPT_ID, safe=""))
    payload = json.dumps({
        "function": function_name,
        "devMode": dev_mode,
        "parameters": params or [],
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Authorization": "Bearer " + b.access_token(),
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as exc:
        return None, "HTTP %d: %s" % (exc.code, exc.read().decode(errors="replace")[:900])
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    fn = sys.argv[1]
    dev_mode = "--nondev" not in sys.argv

    print("執行雲端函式: %s (devMode=%s)" % (fn, dev_mode))
    out, err = run_function(fn, dev_mode)
    if err:
        print("❌ 失敗: %s" % err)
        if "NOT_FOUND" in err:
            print("   -> 請到 https://script.google.com/home/usersettings 開啟 Google Apps Script API")
        return 2
    print("回應: %s" % json.dumps(out, ensure_ascii=False, indent=2)[:2000])
    if out.get("error"):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
