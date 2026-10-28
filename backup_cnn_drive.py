#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CNN 共用資料夾 -> 自己的 Google Drive 智慧備份 (Drive API v3)

功能:
  - 防重複: 同名檔案已存在就跳過, 不會產生「...的複本」
  - 智慧更新: 用 appProperties 記錄來源 modifiedTime, 來源有更新才取代
  - 無限層級: 子資料夾遞迴同步
  - 可重複執行: 增量同步, 中斷後重跑會自動接續 (可分多次完成)

憑證: 複用 clasp 的 OAuth refresh token (~/.clasprc.json), 不需額外設定。

用法:
    python backup_cnn_drive.py             # 執行備份
    python backup_cnn_drive.py --dry-run   # 只列出將做的變更, 不動檔案
    python backup_cnn_drive.py --verify    # 只比對兩邊差異
    python backup_cnn_drive.py --max-seconds 300   # 限時, 到點安全中斷
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

DRIVE = "https://www.googleapis.com/drive/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
TARGET_NAME = "CNN課程備份"
FOLDER_MIME = "application/vnd.google-apps.folder"
SRC_MOD_KEY = "srcMod"
SRC_ID_KEY = "srcId"
MAX_LIST = 40  # 差異清單最多印幾筆 (其餘以「… 其餘 N 筆省略」帶過)

# 選用: 若設定此環境變數 (Apps Script 複製用 Web App 的 /exec 網址),
# 備份模式就能在雲端真正複製檔案內容。未設定時, 備份模式遇到需要複製的檔案會直接報錯。
WEBAPP_URL = os.environ.get("CNN_CLONE_WEBAPP_URL", "").strip()

_token = {"access_token": None, "expiry": 0.0}


# ---- 本機設定 (全部不進版控; 見 README「首次設定」) ----
# 每個設定都是「環境變數優先, 其次同名 .txt 檔」, 檔案都列在 .gitignore。
def read_local_file(name):
    path = os.path.join(HERE, name)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig") as fh:
            return fh.read().strip()
    return ""


def local_setting(env_var, filename, hint):
    val = os.environ.get(env_var, "").strip() or read_local_file(filename)
    if not val:
        sys.exit("缺少設定: %s\n  請設定環境變數 %s, 或建立 %s\n  %s"
                 % (env_var, env_var, os.path.join(HERE, filename), hint))
    return val


def source_folder_id():
    """老師共用資料夾 ID (來源)。"""
    return local_setting("CNN_CLONE_SOURCE_ID", "source_id.txt",
                         "內容為來源資料夾 ID (Drive 網址 /folders/<ID> 的那段)")


def source_id():
    """source_folder_id() 的別名, 讓呼叫端讀起來像常數。"""
    return source_folder_id()


def bridge_url():
    """cloneBridge Web App 的 /exec 網址。"""
    return local_setting("CNN_CLONE_WEBAPP_URL", "bridge_url.txt",
                         "內容為 Web App 的 /exec 網址 (用 python gs_deploy_webapp.py 部署後會自動寫入)")


def bridge_secret():
    """cloneBridge Web App 的共享密鑰。"""
    return local_setting("CNN_CLONE_BRIDGE_SECRET", "bridge_secret.txt",
                         "內容為自己設定的密鑰, 例如 python3 -c 'import secrets;print(secrets.token_hex(16))' 產生的字串")


def clasp_script_id():
    """Apps Script 專案 ID (scriptId)。不是憑證, 但屬於「哪個專案」的設定, 放在 .clasp.json。"""
    path = os.path.join(HERE, ".clasp.json")
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8-sig") as fh:
        return (json.load(fh) or {}).get("scriptId", "")


def load_clasprc():
    path = os.path.join(os.path.expanduser("~"), ".clasprc.json")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    tok = data["tokens"]["default"]
    return tok["client_id"], tok["client_secret"], tok["refresh_token"]


def access_token():
    if _token["access_token"] and time.time() < _token["expiry"] - 60:
        return _token["access_token"]
    cid, csec, rtok = load_clasprc()
    body = urllib.parse.urlencode({
        "client_id": cid,
        "client_secret": csec,
        "refresh_token": rtok,
        "grant_type": "refresh_token",
    }).encode()
    with urllib.request.urlopen(TOKEN_URL, body, timeout=30) as resp:
        out = json.loads(resp.read().decode())
    _token["access_token"] = out["access_token"]
    _token["expiry"] = time.time() + int(out.get("expires_in", 3600))
    return _token["access_token"]


def api(method, path, params=None, body=None, retries=6):
    """Drive API 呼叫, 內建 token 重新整理與 403/429/5xx 指數退避重試。"""
    params = dict(params or {})
    params.setdefault("supportsAllDrives", "true")
    url = DRIVE + path + "?" + urllib.parse.urlencode(params)
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": "Bearer " + access_token()}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            last = "HTTP %d: %s" % (exc.code, detail[:300])
            if exc.code in (403, 429, 500, 502, 503) and attempt < retries - 1:
                wait = min(60, 2 ** attempt)
                print("    ! %s -> %ds 後重試" % (last.split(":")[0], wait), flush=True)
                time.sleep(wait)
                continue
            break
        except urllib.error.URLError as exc:
            last = str(exc)
            if attempt < retries - 1:
                time.sleep(min(60, 2 ** attempt))
                continue
            break
    raise RuntimeError("%s %s -> %s" % (method, path, last))


def list_children(folder_id, page_size=1000):
    """列出資料夾直接子項, 自動翻頁。"""
    items, page = [], None
    while True:
        params = {
            "q": "'%s' in parents and trashed = false" % folder_id,
            "pageSize": page_size,
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,size,md5Checksum,appProperties)",
            "orderBy": "folder,name",
        }
        if page:
            params["pageToken"] = page
        out = api("GET", "/files", params)
        items.extend(out.get("files", []))
        page = out.get("nextPageToken")
        if not page:
            return items


def index_by_name(items):
    idx = {}
    for it in items:
        idx.setdefault(it["name"], it)
    return idx


def print_paths(paths, mark="-", limit=None):
    """列出差異清單; 超過上限只印前幾筆 (避免幾千行 log 蓋掉重點)。"""
    cap = MAX_LIST if limit is None else limit
    for p in paths[:cap]:
        print("    %s %s" % (mark, p))
    if len(paths) > cap:
        print("    … 其餘 %d 筆省略" % (len(paths) - cap))


def find_or_create_target():
    """找目的地資料夾, 沒有就建立 (沿用 Apps Script 的名稱)。"""
    out = api("GET", "/files", {
        "q": "name = '%s' and mimeType = '%s' and 'root' in parents and trashed = false"
             % (TARGET_NAME, FOLDER_MIME),
        "fields": "files(id,name,modifiedTime)",
        "pageSize": 10,
    })
    files = out.get("files", [])
    if files:
        return files[0]["id"], False
    made = api("POST", "/files", {"fields": "id,name"}, {
        "name": TARGET_NAME,
        "mimeType": FOLDER_MIME,
        "parents": ["root"],
    })
    return made["id"], True


def is_source_newer(src, dst):
    """比對來源與備份的檔案是否需要更新。"""
    tracked = (dst.get("appProperties") or {}).get(SRC_MOD_KEY)
    if tracked:
        return src["modifiedTime"] > tracked
    # 沒有追蹤紀錄 (舊版 Apps Script 建的) -> 退回 md5 比對
    if src.get("md5Checksum") and dst.get("md5Checksum"):
        return src["md5Checksum"] != dst["md5Checksum"]
    return src["modifiedTime"] > dst["modifiedTime"]


def content_differs(src, dst):
    """比對「實際內容」是否不同: 大小 / 0 byte 空檔案 / md5。

    重點: 中繼資料 (modifiedTime、appProperties) 相同, 內容也可能是壞的,
    所以驗證必須看 size 與 md5Checksum, 不能只看時間戳。
    """
    s_size, d_size = src.get("size"), dst.get("size")
    if s_size is not None and d_size is not None:
        if int(s_size) != int(d_size):
            return True
        if int(d_size) == 0 and int(s_size) > 0:
            return True
    s_md5, d_md5 = src.get("md5Checksum"), dst.get("md5Checksum")
    if s_md5 and d_md5 and s_md5 != d_md5:
        return True
    return False


def copy_via_webapp(src, dest_parent_id):
    """透過 Apps Script Web App 在雲端複製檔案 (內容由 Apps Script 端負責)。"""
    url = WEBAPP_URL + "?" + urllib.parse.urlencode({
        "srcId": src["id"],
        "name": src["name"],
        "parentId": dest_parent_id,
    })
    with urllib.request.urlopen(url, timeout=180) as resp:
        out = json.loads(resp.read().decode())
    if not out.get("id"):
        raise RuntimeError("Web App 複製失敗: %s" % out)
    return out


def copy_file(src, dest_parent_id):
    """複製檔案到目的地。

    ⚠ 本腳本用的 clasp 憑證只有 drive.file + drive.metadata.readonly,
      「沒有」來源檔案的讀取權, 因此無法自行下載/上傳內容。
      以前的版本用 POST /files 只建了中繼資料, 結果產生 0 byte 空檔案 (PDF 打不開)。
      現在: 沒設定 Web App 就直接報錯, 絕不再產生空檔案。
    """
    if not WEBAPP_URL:
        raise RuntimeError(
            "無法複製「%s」: 目前憑證沒有來源檔的讀取權 (drive.file 範圍), 無法取得內容。\n"
            "  請改用 Apps Script 的 startSmartCloneCNN 執行複製,\n"
            "  或設定環境變數 CNN_CLONE_WEBAPP_URL 指向複製用的 Web App。" % src["name"])
    made = copy_via_webapp(src, dest_parent_id)
    # appProperties 可能被忽略, 確保補寫一次
    if (made.get("appProperties") or {}).get(SRC_MOD_KEY) != src["modifiedTime"]:
        made = api("PATCH", "/files/" + made["id"], {"fields": "id,appProperties"}, {
            "appProperties": {
                SRC_MOD_KEY: src["modifiedTime"],
                SRC_ID_KEY: src["id"],
            },
        })
    return made


def do_copy(src, dst_id, stats):
    """複製單一檔案; 失敗時記錄下來但不中斷整個同步。"""
    try:
        copy_file(src, dst_id)
        return True
    except Exception as exc:
        stats["failed"] += 1
        print("    ❌ 複製失敗: %s" % exc)
        return False


def sync_folder(src_id, dst_id, rel_path, stats, deadline):
    if deadline and time.time() >= deadline:
        stats["timeout"] = True
        return
    src_items = list_children(src_id)
    dst_items = index_by_name(list_children(dst_id))

    # --- 檔案 ---
    for src in src_items:
        if src["mimeType"] == FOLDER_MIME:
            continue
        if deadline and time.time() >= deadline:
            stats["timeout"] = True
            return
        dst = dst_items.get(src["name"])
        if dst is None:
            stats["added"] += 1
            print("  + %s%s" % (rel_path, src["name"]))
            if not stats["dry"]:
                do_copy(src, dst_id, stats)
        elif content_differs(src, dst):
            stats["broken"] += 1
            print("  🩹 %s%s (備份內容不符或 0 byte 空檔, 重新複製)" % (rel_path, src["name"]))
            if not stats["dry"] and do_copy(src, dst_id, stats):
                api("DELETE", "/files/" + dst["id"])
        elif is_source_newer(src, dst):
            stats["updated"] += 1
            print("  ~ %s%s (取代舊檔)" % (rel_path, src["name"]))
            if not stats["dry"] and do_copy(src, dst_id, stats):
                api("DELETE", "/files/" + dst["id"])
        else:
            stats["same"] += 1

    # --- 子資料夾 (遞迴, 無限層級) ---
    for src in src_items:
        if src["mimeType"] != FOLDER_MIME:
            continue
        if deadline and time.time() >= deadline:
            stats["timeout"] = True
            return
        dst = dst_items.get(src["name"])
        if dst is None:
            stats["added"] += 1
            print("  + %s%s/" % (rel_path, src["name"]))
            if stats["dry"]:
                continue
            made = api("POST", "/files", {"fields": "id,name"}, {
                "name": src["name"],
                "mimeType": FOLDER_MIME,
                "parents": [dst_id],
            })
            dst = made
        sync_folder(src["id"], dst["id"], rel_path + src["name"] + "/", stats, deadline)


def collect_missing(src_id, rel_path, rep):
    """備份缺少整個資料夾時, 遞迴把子樹裡的項目逐一記為缺少。

    為什麼要遞迴: 舊版只記「這個資料夾缺少」1 筆就停, 資料夾底下的檔案不會被算到。
    實測曾有「缺少 372」實際上是 1,793 個檔案 (整個 LocalCNN/dataset/gender/Woman/
    與 rps/ 都沒備份), 缺口被嚴重低估。
    """
    for src in list_children(src_id):
        if src["mimeType"] == FOLDER_MIME:
            rep["missing"].append(rel_path + src["name"] + "/")
            collect_missing(src["id"], rel_path + src["name"] + "/", rep)
        else:
            rep["missing"].append(rel_path + src["name"])


def verify(src_id, dst_id, rel_path, rep):
    """比對來源與備份, 回報缺漏/過期/多餘。"""
    src_items = list_children(src_id)
    dst_index = index_by_name(list_children(dst_id))
    for src in src_items:
        dst = dst_index.get(src["name"])
        if src["mimeType"] == FOLDER_MIME:
            if dst is None:
                rep["missing"].append(rel_path + src["name"] + "/")
                collect_missing(src["id"], rel_path + src["name"] + "/", rep)
            else:
                verify(src["id"], dst["id"], rel_path + src["name"] + "/", rep)
        elif dst is None:
            rep["missing"].append(rel_path + src["name"])
        elif content_differs(src, dst):
            rep["broken"].append(rel_path + src["name"])
        elif is_source_newer(src, dst):
            rep["outdated"].append(rel_path + src["name"])
        else:
            rep["ok"] += 1
    for name in dst_index:
        if not any(s["name"] == name for s in src_items):
            rep["extra"].append(rel_path + name)


def main():
    ap = argparse.ArgumentParser(description="CNN 共用資料夾備份到自己的雲端硬碟")
    ap.add_argument("--dry-run", action="store_true", help="只預覽, 不修改任何檔案")
    ap.add_argument("--verify", action="store_true", help="只比對差異, 不修改任何檔案")
    ap.add_argument("--max-seconds", type=int, default=0,
                    help="超過秒數就安全中斷, 重跑同一指令可續傳 (預設不限)")
    args = ap.parse_args()

    mode = "比對模式" if args.verify else ("預覽模式" if args.dry_run else "備份模式")
    print("=" * 64)
    print("CNN 課程備份 — %s" % mode)
    print("=" * 64)

    dst_id, created = find_or_create_target()
    if created:
        print("  建立目的地資料夾: %s (%s)" % (TARGET_NAME, dst_id))
    else:
        print("  目的地: %s (%s)" % (TARGET_NAME, dst_id))

    if args.verify:
        rep = {"ok": 0, "missing": [], "outdated": [], "extra": [], "broken": []}
        verify(source_folder_id(), dst_id, "", rep)
        print("\n===== 比對結果 (含內容比對: 大小/md5) =====")
        print("  一致: %d" % rep["ok"])
        print("  缺少: %d" % len(rep["missing"]))
        print_paths(rep["missing"])
        print("  過期: %d" % len(rep["outdated"]))
        print_paths(rep["outdated"])
        print("  內容不符/空檔案: %d" % len(rep["broken"]))
        print_paths(rep["broken"], "✗")
        print("  多餘: %d" % len(rep["extra"]))
        print_paths(rep["extra"], "+")
        bad = len(rep["missing"]) + len(rep["outdated"]) + len(rep["broken"])
        print("\nRESULT: %s" % ("PERFECT_MATCH 完全一致" if bad == 0
                                else "DIFFERENCES_FOUND 有差異"))
        if rep["broken"]:
            print("提示: 「內容不符/空檔案」的檔案無法用本腳本複製 (憑證權限不足),")
            print("      請執行 Apps Script 的 startSmartCloneCNN 修復。")
        return 0 if bad == 0 else 2

    deadline = time.time() + args.max_seconds if args.max_seconds > 0 else None
    stats = {"added": 0, "updated": 0, "same": 0, "broken": 0, "failed": 0,
             "dry": args.dry_run, "timeout": False}

    print("\n掃描與同步中...")
    sync_folder(source_folder_id(), dst_id, "", stats, deadline)

    print("\n" + "=" * 64)
    label = "預覽完成" if args.dry_run else "同步完成"
    print("%s: 新增 %d, 取代 %d, 修復壞檔 %d, 已一致 %d" %
          (label, stats["added"], stats["updated"], stats["broken"], stats["same"]))
    if stats["failed"]:
        print("⚠ 有 %d 個檔案複製失敗 — 請改用 Apps Script 的 startSmartCloneCNN 執行複製" %
              stats["failed"])
    if stats["broken"] and not stats["dry"] and not stats["failed"]:
        print("✅ 已修復 %d 個損壞/空檔案" % stats["broken"])
    if stats["timeout"]:
        print("⏳ 已達時間上限, 安全中斷 — 再次執行同一指令即可續傳")
    if not args.dry_run:
        print("目的地: https://drive.google.com/drive/folders/%s" % dst_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
