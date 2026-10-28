// ============================================================
// cloneBridge — 讓本機 Python 能觸發「雲端真正複製」的 Web App 橋接
//
// 為什麼需要它:
//   本機 Python 用的 clasp 憑證只有 drive.file + drive.metadata.readonly,
//   讀不到老師共用資料夾的檔案內容, 所以無法自行複製 (會產生 0 byte 空檔案)。
//   Apps Script 有完整 Drive 權限, 由它執行複製才是正確做法。
//
// 部署方式:
//   appsscript.json 已設定 "webapp": executeAs=USER_DEPLOYING, access=ANYONE_ANONYMOUS
//   clasp create-deployment  ->  取得 deploymentId
//   網址: https://script.google.com/macros/s/<deploymentId>/exec
//
// 動作 (都需要帶 secret):
//   ?action=ping&secret=...   檢查橋接是否可用
//   ?action=sync&secret=...   執行 startSmartCloneCNN (複製缺少/損壞的檔案), 回傳統計
//   ?action=extra&secret=...  列出備份裡「來源已經沒有」的多餘檔案 (唯讀, 不會改動任何檔案)
//   ?action=trash&secret=...  刪除多餘檔案 (移到垃圾桶); 可加 &name=檔名 只刪指定那一個。
//                             安全護欄: 只會刪「來源沒有的檔案」, 來源還有的檔案一律不動。
//
// 安全: 沒有 secret 一律拒絕。不想再用時刪除部署即可:
//   clasp delete-deployment <deploymentId>
//
// 密鑰與來源資料夾 ID「不寫在程式碼裡」(repo 已 public), 一律放 Script Properties:
//   BRIDGE_SECRET      共享密鑰
//   SOURCE_FOLDER_ID   來源資料夾 ID
// 首次佈建 (雲端還沒有密鑰時才有效, 設定完就永久關閉這條路):
//   ?action=bootstrap&secret=<新密鑰>&source=<來源資料夾ID>
// 日後要換密鑰 (需帶目前密鑰):
//   ?action=rotate&secret=<舊密鑰>&new=<新密鑰>
// ============================================================

var BRIDGE_TARGET_NAME = 'CNN課程備份';

function cloneBridgeProps() {
  return PropertiesService.getScriptProperties();
}

function cloneBridgeSecret() {
  return cloneBridgeProps().getProperty('BRIDGE_SECRET') || '';
}

function cloneBridgeSourceId() {
  return cloneBridgeProps().getProperty('SOURCE_FOLDER_ID') || '';
}

// 在我的雲端硬碟根目錄找目的地資料夾 (找不到回 null)
function cloneBridgeTargetFolder() {
  var it = DriveApp.getRootFolder().getFolders();
  while (it.hasNext()) {
    var f = it.next();
    if (f.getName() === BRIDGE_TARGET_NAME) {
      return f;
    }
  }
  return null;
}

// 遞迴收集資料夾內的檔案 -> {相對路徑: File}
function cloneBridgeCollectFiles(folder, prefix, out) {
  var files = folder.getFiles();
  while (files.hasNext()) {
    var f = files.next();
    out[prefix + f.getName()] = f;
  }
  var subs = folder.getFolders();
  while (subs.hasNext()) {
    var sf = subs.next();
    cloneBridgeCollectFiles(sf, prefix + sf.getName() + '/', out);
  }
  return out;
}

// 備份裡「來源已經沒有」的檔案 (與 backup_cnn_drive.py --verify 的「多餘」同一套判斷)
function cloneBridgeExtraFiles() {
  var target = cloneBridgeTargetFolder();
  if (target === null) {
    return null;
  }
  var src = cloneBridgeCollectFiles(DriveApp.getFolderById(cloneBridgeSourceId()), '', {});
  var dst = cloneBridgeCollectFiles(target, '', {});
  var extra = [];
  for (var p in dst) {
    if (!(p in src)) {
      extra.push({ path: p, file: dst[p] });
    }
  }
  extra.sort(function (a, b) { return a.path < b.path ? -1 : 1; });
  return extra;
}

// 刪除多餘檔案 (移到垃圾桶, 可還原)。nameFilter 有值時只處理符合的檔案。
// 安全護欄: 只從「多餘清單」挑, 所以來源還有的檔案不可能被刪。
function cloneBridgeTrashExtra(nameFilter) {
  var extra = cloneBridgeExtraFiles();
  if (extra === null) {
    return { ok: false, error: '找不到目的地資料夾: ' + BRIDGE_TARGET_NAME };
  }
  var trashed = [];
  var skipped = [];
  for (var i = 0; i < extra.length; i++) {
    var item = extra[i];
    if (nameFilter && item.path !== nameFilter && item.file.getName() !== nameFilter) {
      skipped.push(item.path);
      continue;
    }
    item.file.setTrashed(true);
    trashed.push(item.path);
  }
  return { ok: true, trashed: trashed, skipped: skipped, extraTotal: extra.length };
}

function doGet(e) {
  return cloneBridgeHandle(e);
}

function doPost(e) {
  return cloneBridgeHandle(e);
}

function cloneBridgeJson(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function cloneBridgeHandle(e) {
  var p = (e && e.parameter) || {};
  var props = cloneBridgeProps();
  var current = props.getProperty('BRIDGE_SECRET') || '';

  // 一次性佈建: 雲端還沒有密鑰時才有效, 設定完這條路就永久關閉
  if (p.action === 'bootstrap') {
    if (current) {
      return cloneBridgeJson({ ok: false, error: 'already initialized' });
    }
    if (!p.secret || !p.source) {
      return cloneBridgeJson({ ok: false, error: 'need secret & source' });
    }
    props.setProperty('BRIDGE_SECRET', p.secret);
    props.setProperty('SOURCE_FOLDER_ID', p.source);
    return cloneBridgeJson({ ok: true, initialized: true });
  }

  if (!current || p.secret !== current) {
    return cloneBridgeJson({ ok: false, error: 'unauthorized' });
  }
  try {
    if (p.action === 'rotate') {
      if (!p['new']) {
        return cloneBridgeJson({ ok: false, error: 'need new' });
      }
      props.setProperty('BRIDGE_SECRET', p['new']);
      return cloneBridgeJson({ ok: true, rotated: true });
    }
    if (p.action === 'ping') {
      return cloneBridgeJson({
        ok: true,
        email: Session.getActiveUser().getEmail(),
        scriptId: ScriptApp.getScriptId(),
        time: new Date().toISOString()
      });
    }
    if (p.action === 'sync') {
      var stats = startSmartCloneCNN();
      if (!stats) {
        return cloneBridgeJson({ ok: false, error: 'busy: 另一個同步正在執行中' });
      }
      return cloneBridgeJson({ ok: true, stats: stats });
    }
    if (p.action === 'extra') {
      var extra = cloneBridgeExtraFiles();
      if (extra === null) {
        return cloneBridgeJson({ ok: false, error: '找不到目的地資料夾: ' + BRIDGE_TARGET_NAME });
      }
      var paths = [];
      for (var i = 0; i < extra.length; i++) {
        paths.push(extra[i].path);
      }
      return cloneBridgeJson({ ok: true, count: paths.length, extra: paths });
    }
    if (p.action === 'trash') {
      return cloneBridgeJson(cloneBridgeTrashExtra(p.name || ''));
    }
    return cloneBridgeJson({ ok: false, error: 'unknown action: ' + p.action });
  } catch (err) {
    return cloneBridgeJson({ ok: false, error: String(err) });
  }
}
