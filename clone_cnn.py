#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clonecnn 主流程: 觸發雲端 Apps Script 真正複製缺少/損壞的檔案 → 驗證兩邊一致。

為什麼要這樣做:
    本機 Python 憑證只有 drive.file + drive.metadata.readonly, 讀不到來源檔內容,
    自己複製只會產生 0 byte 空檔案。真正複製必須由 Apps Script (有完整 Drive 權限) 執行,
    本腳本透過 cloneBridge Web App 觸發它。

用法:
    python clone_cnn.py              # 同步 + 驗證 (預設)
    python clone_cnn.py --if-needed  # 先驗證, 已完全一致就跳過雲端同步 (不空轉)
    python clone_cnn.py --verify     # 只驗證, 不觸發複製
    python clone_cnn.py --dry-run    # 只列出缺少/損壞的檔案, 不做任何事

輸出關鍵字:
    RESULT: PERFECT_MATCH 完全一致   -> 備份完整 (exit 0)
    RESULT: DIFFERENCES_FOUND 有差異 -> 還有差異 (exit 2)
    RESULT: BRIDGE_ERROR             -> 無法觸發雲端複製 (exit 3)
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backup_cnn_drive as b  # noqa: E402

# 設定一律放在本機 (不進版控): 環境變數優先, 其次同名 .txt 檔。
#   CNN_CLONE_WEBAPP_URL / bridge_url.txt         -> cloneBridge 的 /exec 網址
#   CNN_CLONE_BRIDGE_SECRET / bridge_secret.txt   -> cloneBridge 的密鑰
#   CNN_CLONE_SOURCE_ID / source_id.txt           -> 來源資料夾 ID
MAX_ROUNDS = 6
ROUND_TIMEOUT = 320
BUSY_WAIT = 45        # 雲端回 busy 時, 等幾秒再續傳 (單次執行上限約 6 分鐘)
MAX_BUSY_WAITS = 20   # 最多等幾次鎖, 避免無限等待


def bridge_call(url, secret, action, timeout=ROUND_TIMEOUT):
    full = url + "?" + urllib.parse.urlencode({"action": action, "secret": secret})
    req = urllib.request.Request(full, headers={"User-Agent": "clonecnn/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode(errors="replace")
        return json.loads(body), None
    except urllib.error.HTTPError as exc:
        return None, "HTTP %d: %s" % (exc.code, exc.read().decode(errors="replace")[:300])
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def find_target_readonly():
    out = b.api("GET", "/files", {
        "q": "name = '%s' and mimeType = '%s' and 'root' in parents and trashed = false"
             % (b.TARGET_NAME, b.FOLDER_MIME),
        "fields": "files(id,name)",
        "pageSize": 10,
    })
    files = out.get("files", [])
    return files[0]["id"] if files else None


def run_verify(dst_id):
    rep = {"ok": 0, "missing": [], "outdated": [], "extra": [], "broken": []}
    b.verify(b.source_folder_id(), dst_id, "", rep)
    return rep


def print_report(rep):
    print("\n===== 比對結果 (含內容比對: 大小/md5) =====")
    print("  一致            : %d" % rep["ok"])
    print("  缺少            : %d" % len(rep["missing"]))
    b.print_paths(rep["missing"])
    print("  過期            : %d" % len(rep["outdated"]))
    b.print_paths(rep["outdated"])
    print("  內容不符/空檔案 : %d" % len(rep["broken"]))
    b.print_paths(rep["broken"], "✗")
    print("  多餘            : %d" % len(rep["extra"]))
    b.print_paths(rep["extra"], "+")
    bad = len(rep["missing"]) + len(rep["outdated"]) + len(rep["broken"])
    return bad


def do_sync(url, secret, max_rounds=None):
    """請雲端 Apps Script 複製缺少/損壞的檔案, 直到沒有東西要複製為止。

    重點: 雲端回 "busy" 代表「上一個同步還在跑」(LockService 未放開),
    進度已保留在雲端, 這時要等它放開再續傳, 不能當成失敗中止。
    連線被關閉 (Remote end closed connection) 同理: 雲端仍在執行, 下一輪續傳即可。
    """
    rounds = 0          # 真的拿到雲端統計的輪數 (busy 不計)
    busy_waits = 0      # 等鎖放開的次數
    limit = MAX_ROUNDS if max_rounds is None else max_rounds
    while rounds < limit and busy_waits < MAX_BUSY_WAITS:
        rounds += 1
        print("\n--- 第 %d 輪: 請雲端 Apps Script 同步 ---" % rounds, flush=True)
        out, err = bridge_call(url, secret, "sync")
        if err:
            print("  ⚠ 呼叫失敗: %s" % err)
            print("  (若是執行時間超過上限, 進度已保留, 下一輪會續傳)")
            time.sleep(3)
            continue
        if not out.get("ok"):
            detail = str(out.get("error") or "")
            if "busy" in detail:
                rounds -= 1  # busy 不算一輪同步, 只是等鎖
                busy_waits += 1
                print("  ⏳ %s — 等 %d 秒後續傳 (進度已保留)" % (detail, BUSY_WAIT), flush=True)
                time.sleep(BUSY_WAIT)
                continue
            print("  ⚠ 雲端回報: %s" % detail)
            return False
        st = out.get("stats") or {}
        added = int(st.get("added", 0))
        updated = int(st.get("updated", 0))
        broken = int(st.get("broken", 0))
        skipped = int(st.get("skipped", 0))
        print("  新增 %d / 取代 %d / 修復壞檔 %d / 跳過 %d" %
              (added, updated, broken, skipped))
        if added + updated + broken == 0:
            print("  ✅ 雲端已無需複製的檔案")
            return True
        print("  仍有複製動作, 再跑一輪確認沒有漏 (可能是執行時間上限中斷)")
    if busy_waits >= MAX_BUSY_WAITS:
        print("  ⚠ 等鎖超過 %d 次, 請稍後再執行一次以續傳" % MAX_BUSY_WAITS)
    else:
        print("  ⚠ 已達最大輪數 (%d), 請再執行一次以續傳" % limit)
    return True


def main():
    ap = argparse.ArgumentParser(description="CNN 備份: 觸發雲端複製 + 驗證")
    ap.add_argument("--verify", action="store_true", help="只驗證, 不觸發複製")
    ap.add_argument("--dry-run", action="store_true", help="只列出差異, 不觸發複製")
    ap.add_argument("--if-needed", action="store_true",
                    help="先驗證, 已完全一致就跳過雲端同步 (避免空轉)")
    ap.add_argument("--max-rounds", type=int, default=MAX_ROUNDS,
                    help="同步最多跑幾輪 (預設 %d); 大檔案庫可調高, 例如 30" % MAX_ROUNDS)
    args = ap.parse_args()

    print("=" * 64)
    print("CNN 課程備份 — 同步 + 驗證")
    print("=" * 64)

    dst_id = find_target_readonly()
    if not dst_id:
        print("❌ 找不到目的地資料夾「%s」" % b.TARGET_NAME)
        return 3
    print("  目的地: %s (%s)" % (b.TARGET_NAME, dst_id))

    url = os.environ.get("CNN_CLONE_WEBAPP_URL", "").strip() or b.read_local_file("bridge_url.txt")
    if not url:
        print("\n⚠ 尚未設定複製用 Web App (bridge_url.txt), 無法自動複製。")
        print("  請先執行: python gs_deploy_webapp.py")
        print("  (或到 Apps Script 編輯器執行 startSmartCloneCNN)")
        rep = run_verify(dst_id)
        bad = print_report(rep)
        print("\nRESULT: %s" % ("PERFECT_MATCH 完全一致" if bad == 0
                                else "DIFFERENCES_FOUND 有差異"))
        return 0 if bad == 0 else 2

    print("  複製通道: %s..." % url[:64])

    if args.verify or args.dry_run:
        print("\n(略過複製, 只做檢查)")
    else:
        if args.if_needed:
            print("\n(先檢查, 已完全一致就不觸發雲端同步)")
            rep = run_verify(dst_id)
            if print_report(rep) == 0:
                print("\nRESULT: PERFECT_MATCH 完全一致 (已是最新, 略過同步)")
                print("目的地: https://drive.google.com/drive/folders/%s" % dst_id)
                return 0
            print("\n  發現差異, 開始觸發雲端同步...", flush=True)
        if not do_sync(url, b.bridge_secret(), args.max_rounds):
            print("\nRESULT: BRIDGE_ERROR 無法觸發雲端複製")
            return 3

    print("\n--- 驗證 ---", flush=True)
    rep = run_verify(dst_id)
    bad = print_report(rep)
    print("\nRESULT: %s" % ("PERFECT_MATCH 完全一致" if bad == 0
                            else "DIFFERENCES_FOUND 有差異"))
    if bad:
        print("提示: 若「缺少/內容不符」一直存在, 請看 README.md 的疑難排解。")
    print("目的地: https://drive.google.com/drive/folders/%s" % dst_id)
    return 0 if bad == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
