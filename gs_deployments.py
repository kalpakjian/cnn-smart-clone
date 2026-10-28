#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查詢 Apps Script 專案的部署清單 (唯讀)。

用法:
    python gs_deployments.py
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backup_cnn_drive as b  # noqa: E402

SCRIPT_ID = b.clasp_script_id()
API = "https://script.googleapis.com/v1"


def call(path):
    url = API + path
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + b.access_token(),
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return {"__error__": "HTTP %d: %s" % (exc.code, exc.read().decode(errors="replace")[:600])}


def main():
    print("Script ID: %s" % SCRIPT_ID)
    out = call("/projects/%s/deployments" % urllib.parse.quote(SCRIPT_ID, safe=""))
    if "__error__" in out:
        print("查詢失敗: %s" % out["__error__"])
        return 1
    deps = out.get("deployments", [])
    print("部署數量: %d" % len(deps))
    for d in deps:
        eps = d.get("entryPoints") or []
        print("-" * 56)
        print("  deploymentId : %s" % d.get("deploymentId"))
        print("  config       : %s" % d.get("deploymentConfig"))
        print("  entryPoints  : %s" % [list(e.keys()) for e in eps])
        for e in eps:
            if e.get("webApp"):
                print("  webApp       : %s" % e["webApp"])
                print("  webApp URL   : %s" % (e["webApp"].get("url")
                      or "https://script.google.com/macros/s/%s/exec" % d.get("deploymentId")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
