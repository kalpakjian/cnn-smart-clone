# CNN 備份 — 架構、正確用法與踩坑記錄

> 2026/10/07 重寫。原本的認知（「Python 腳本會把 CNN 資料夾備份到雲端」）是**錯的**，
> 請務必看過這份說明。
>
> ✅ **2026/10/28 起這個 repo 是 public，而且不含任何密鑰／網址／資料夾 ID。**
> 密鑰與來源資料夾 ID 都改放「本機檔案或環境變數」與 Apps Script 的 Script Properties，
> 只有 `sourceId`（不是憑證）留在 `.clasp.json`。看程式沒問題，但要自己跑就得做
> 下面的「首次設定」。

## 一句話結論

**檔案內容只能由 Apps Script 複製**（它有完整 Drive 權限）。本機 clasp 憑證只有
`drive.file` + `drive.metadata.readonly`，**讀不到來源檔內容**，自己複製只會產生 **0 byte 空檔案**。

## 現在的架構

```
clone_cnn.py ──HTTP──► cloneBridge Web App (Apps Script) ──► 真正複製檔案內容
      └──► 驗證（比對 size / md5Checksum）
```

- `bridge_url.txt`：cloneBridge Web App 的 `/exec` 網址
- `cloneBridge.gs`：`?action=sync` → 執行 `startSmartCloneCNN`，回傳複製統計
- 為什麼不用 `clasp run`：Apps Script API 未啟用，會回 `NOT_FOUND`

## 首次設定（clone 下來的人必看）

公開 repo 裡**沒有任何憑證**，三個設定要自己放（全部已列在 `.gitignore`）：
環境變數優先，沒有環境變數才讀同名 `.txt` 檔。

| 設定 | 環境變數 | 本機檔案 | 內容 |
|---|---|---|---|
| 來源資料夾 ID | `CNN_CLONE_SOURCE_ID` | `source_id.txt` | 要備份的 Drive 資料夾 ID |
| Web App 網址 | `CNN_CLONE_WEBAPP_URL` | `bridge_url.txt` | 自己的 cloneBridge `/exec` 網址 |
| 共享密鑰 | `CNN_CLONE_BRIDGE_SECRET` | `bridge_secret.txt` | 自己產生的密鑰 |

```bash
# 1) 產生密鑰並寫進本機檔
python3 -c 'import secrets;print(secrets.token_hex(16))' > bridge_secret.txt
printf '%s\n' '<來源資料夾ID>' > source_id.txt

# 2) 把 .gs 推上自己的 Apps Script 專案, 建立/更新部署 (會自動寫入 bridge_url.txt)
clasp push -f && python3 gs_deploy_webapp.py

# 3) 一次性佈建: 把密鑰與來源 ID 寫進 Script Properties (設定完這條路就關閉)
URL=$(cat bridge_url.txt); SECRET=$(cat bridge_secret.txt); SRC=$(cat source_id.txt)
curl -s "$URL?action=bootstrap&secret=$SECRET&source=$SRC"

# 4) 確認通道活著
python3 bridge_test.py          # RESULT: BRIDGE_OK ✅
```

缺少設定時, 腳本會直接告訴你還缺哪一個（不會像舊版一樣偷偷用寫死的預設值）。

## 正確用法

```bash
python3 clone_cnn.py --if-needed   # 日常巡檢: 先驗證, 已一致就不觸發雲端同步
python3 clone_cnn.py               # 同步 + 驗證
python3 clone_cnn.py --verify      # 只驗證
python3 clone_cnn.py --dry-run     # 只列出差異
```

（Windows PowerShell 先設 `$env:PYTHONIOENCODING='utf-8'`，路徑換成自己的。）

- 先請雲端同步（複製缺少／損壞的檔案），再驗證兩邊一致
- 成功條件：`RESULT: PERFECT_MATCH 完全一致`
- 大檔案庫請提高輪數：`python3 clone_cnn.py --max-rounds 30`
- 同步很久 → 建議背景執行後輪詢 log（`nohup python3 -u clone_cnn.py --if-needed > run.log 2>&1 &`）

## 歷史：為什麼會出現「打不開」的檔案

舊版 `backup_cnn_drive.py` 的 `copy_file()` 用 `POST /files` 只建立了檔名、資料夾、
`appProperties`，**完全沒有上傳內容** → 產生 **0 byte 空檔案**（PDF/zip/h5 都打不開）。

當時的 `--verify` 只比對 `modifiedTime` / `appProperties`，所以壞檔被誤判為
`PERFECT_MATCH 完全一致`。實際證據（連伺服器端複製也不行）：

```
POST /files/{srcId}/copy -> HTTP 403
"The user has not granted the app 1072944905499 read access to the file ..."
```

## 2026/10/07 已修復的 10 個 0 byte 壞檔

`clone_cnn.py` 透過 Web App 觸發雲端同步，回報「**修復壞檔 10 / 跳過 2165**」，
之後驗證 2,175 個檔案**全部一致**（含 size/md5 內容比對）：

| 檔案 | 大小 |
|---|---|
| 3 IVDC OpenCV.pdf | 1,597,203 |
| Image Recognition-20261005T102736Z-1-001.zip | 89,899,977 |
| Image Recognition/keras_model.h5 | 2,453,432 |
| Image Recognition/labels.txt | 14 |
| Image Recognition/UseModelPhoto.ipynb | 36,158 |
| OpenCVLab/hints.docx | 21,347 |
| OpenCVLab/Matrix_Operations.ipynb | 6,158 |
| OpenCVLab/Pre_Processing.ipynb | 8,328 |
| OpenCVLab/Pre_Processing_Sample.ipynb | 2,046 |
| OpenCVLab/Transformation_and_Filtering.ipynb | 6,283 |

修復機制：`startSmartCloneCNN.gs` 內建 `isBroken`（備份 0 byte 而來源 > 0 → 直接重新複製）。
沒有這個修補的舊版會因為「備份檔時間比較新」而跳過，永遠修不好。

## 2026/10/07 第二批：大小不符的壞檔（備份比來源新 → 永遠跳過）

驗證抓到 `OpenCVLab/Pre_Processing_Sample.ipynb` 內容不符：

| | 大小 | md5 | mimeType | modifiedTime |
|---|---|---|---|---|
| 來源 | 2,046 | `31027ccafa51f1d5f7df7d7fa31908c9` | application/octet-stream | 2026-10-05T07:45 |
| 備份（壞） | 1,577 | `dcc0d6144a7637e57832751d667bad24` | application/json | 2026-10-07T01:25 |

**備份的 modifiedTime 比來源新**，而舊的 `isBroken` 只認「0 byte 空檔案」，
所以雲端同步判定「備份比較新 → 跳過」，連跑兩次都是 `跳過 2175`，永遠修不好
（跟上面那 10 個 0 byte 壞檔是同一個陷阱）。

修法（`startSmartCloneCNN.gs`）：把壞檔判斷從「只看 0 byte」改成「**大小不符就算壞**」：

```js
// 舊: var isBroken = (dstSize === 0 && srcSize > 0);
var isBroken = (srcSize > 0 && dstSize !== srcSize);   // 0 byte 與大小不符都算壞檔
```

上線步驟（**只 `clasp push` 沒用，部署會凍結在舊版**）：

```powershell
clasp push -f
clasp deploy -i <bridge_url.txt 內的 deploymentId> -V <新版本號> -d "..."
# 網址不變 → bridge_url.txt 不用改；再跑 python bridge_test.py 確認 BRIDGE_OK
```

修好後重跑 `clone_cnn.py`：雲端回報 `修復壞檔 1`（新檔案 size 2,046 / md5 `31027cc…`），
驗證 **2,175 個檔案全部一致 → `RESULT: PERFECT_MATCH 完全一致`**。
再跑一次確認可重複執行：`新增 0 / 取代 0 / 修復壞檔 0 / 跳過 2175`，不會無限重複複製。

## 2026/10/15 第三批：來源新增 10 檔 + 清理 1 個多餘檔案

`clone_cnn.py` 跑 2 輪（10/15 00:48–00:51 +08:00）：

```
第 1 輪: 新增 10 / 取代 0 / 修復壞檔 2 / 跳過 2172
第 2 輪: 新增 0 / 取代 0 / 修復壞檔 0 / 跳過 2184   ✅ 雲端已無需複製的檔案
```

驗證：一致 **2,184** / 缺少 0 / 過期 0 / 內容不符 0 / **多餘 1**
→ `RESULT: PERFECT_MATCH 完全一致`。

多餘的那 1 個是 `Image Recognition-20261005T102736Z-1-001.zip`（來源已刪除、備份還留著）。
**「多餘」不影響備份完整性**（缺檔／壞檔才是問題），所以結論仍是 PERFECT_MATCH；
要清掉就用 `cleanup_extra.py`（下一節）：

```powershell
python cleanup_extra.py                                                    # 只列出
python cleanup_extra.py --trash --name "Image Recognition-20261005T102736Z-1-001.zip"
```

清掉後再驗證：一致 **2,187** / 缺少 0 / 過期 0 / 內容不符 0 / **多餘 0**
→ `RESULT: PERFECT_MATCH 完全一致`。

> 來源是老師的**共用活資料夾**，會一直變動（本次掃描期間就從 2,184 變成 2,187），
> 所以「一致」的數字會隨掃描時間不同；**判斷標準是 `PERFECT_MATCH`**
> （缺少／過期／內容不符／多餘都是 0），不是某個固定數字。
> 獨立複查：兩邊遞迴統計都是 **2,187 個檔案 / 17 個資料夾**。

## 2026/10/26 第四批：修正「busy 就中止」與「缺資料夾不遞迴」兩個 bug

這天在 macOS 上從零跑一次完整備份（`~/cnn-smart-clone`，clasp 3.4.1 重新 `clasp login`），
過程暴露兩個會讓人誤判的程式問題，已修好並實測：

### 1. `clone_cnn.py`：雲端回 `busy` 不該中止

`?action=sync` 在雲端回 `busy: 另一個同步正在執行中`（`LockService` 沒放開）時，
舊版直接 `return False` → `RESULT: BRIDGE_ERROR` 收工。但 busy 只代表
**上一輪還在跑、進度已保留在雲端**，正確做法是等鎖放開再續傳。

修法：`busy` 改為 `sleep(45)` 後重試（`BUSY_WAIT`／最多 `MAX_BUSY_WAITS=20` 次），
busy 不佔用「同步輪數」；另外新增 `--max-rounds`（預設 6），大檔案庫可調高。

```powershell
python clone_cnn.py --max-rounds 30
```

### 1b. `--if-needed`：已同步就不要空轉

即使完全一致，`sync` 仍要雲端重掃全樹，而統計幾乎一定被斷線吃掉，
結果是「什麼都不用複製」也要空轉好幾輪（每輪約 6 分鐘）。新增 `--if-needed`：
**先驗證，`PERFECT_MATCH` 就直接結束**，有差異才觸發雲端同步。

```powershell
python clone_cnn.py --if-needed   # 日常巡檢用這個
```

### 2. `backup_cnn_drive.py`：缺整個資料夾時要遞迴列舉

`verify()` 遇到來源有、備份沒有的**資料夾**，舊版只記 1 筆就停、
**不會進去數底下的檔案**，所以缺口被嚴重低估。本次實際狀況：

| 舊版回報 | 實際狀況 |
|---|---|
| 一致 2,781 / 缺少 **372** | 來源 **4,575** 檔，實際缺 **1,793** 檔 |

（372 裡大部分是「缺一個資料夾」的 1 筆，`LocalCNN/dataset/gender/Woman/`、
`LocalCNN/dataset/rps/` 底下 1,400 多個檔案完全沒被算到。）

修法：新增 `collect_missing()`，缺資料夾時遞迴把子樹的檔案與資料夾逐一記為缺少。
比對結果也會更容易讀——差異清單最多印 40 筆，其餘顯示 `… 其餘 N 筆省略`
（`print_paths()`，與 `diagnose_broken.py` 的既有寫法一致）。

### 本次實跑結果

同步 1,793 檔、約 40 分鐘、20 幾輪續傳（每輪 Apps Script 約 6 分鐘上限，
HTTP 回應幾乎每次都被切斷 → **雲端統計永遠拿不到，一律以本機 `--verify` 為準**）：

```
一致            : 4575
缺少            : 0
過期            : 0
內容不符/空檔案 : 0
多餘            : 0
RESULT: PERFECT_MATCH 完全一致
```

獨立複查：來源 **4,575 檔 / 29 資料夾**、備份 **4,575 檔 / 29 資料夾 / 230,968,492 bytes / 0 byte 空檔 0 個**。

> 過程中老師把 `OCR/Untitled0.ipynb` 改名成 `OCR/ocr.ipynb`，備份留下舊檔 → 驗證出現「多餘 1」。
> `cleanup_extra.py --trash --name "OCR/Untitled0.ipynb"` 一樣回報 `BRIDGE_ERROR`
> （`Remote end closed connection without response`），但**雲端其實已執行**：
> 重新查詢備份該檔已不在，再驗證就是「多餘 0」。
> 也就是說 `cleanup_extra.py` 出現連線中斷時，要重新查一次結果，不要直接當失敗重跑。

## 清理「多餘」檔案（來源已刪除、備份還留著）

本機 clasp 憑證只有 `drive.file` + `drive.metadata.readonly`，**沒有刪除權限**
（備份檔是 Apps Script 建立的，本機這個 App 動不了），所以**刪除也一樣要走 cloneBridge**。

| 動作 | 用途 |
|---|---|
| `?action=extra&secret=...` | **唯讀**列出備份裡「來源已經沒有」的檔案 |
| `?action=trash&secret=...` | 刪除多餘檔案（移到垃圾桶）；可加 `&name=檔名` 只刪指定那一個 |

安全護欄：雲端只從「多餘清單」挑檔案，判斷方式與 `clone_cnn.py` 驗證的「多餘」完全相同
（遞迴比對相對路徑），**來源還有的檔案不可能被誤刪**；刪除只是移到垃圾桶，隨時可還原。

```powershell
python cleanup_extra.py            # 只列出（RESULT: NO_EXTRA / FOUND_EXTRA）
python cleanup_extra.py --trash    # 刪除全部多餘檔案（RESULT: TRASHED）
```

## 敏感資訊檢查（2026/10/28 公開化後）

- repo 是 **public**：`gh repo view kalpakjian/cnn-smart-clone --json visibility` → `PUBLIC`。
- **追蹤檔案內沒有**：密鑰、Web App 網址、來源／目的地資料夾 ID、email、Drive 連結。
  - 密鑰：只存在本機 `bridge_secret.txt` 與雲端 Script Properties（`BRIDGE_SECRET`）。
  - Web App 網址：只在本機 `bridge_url.txt`。
  - 來源資料夾 ID：只在本機 `source_id.txt` 與雲端 Script Properties（`SOURCE_FOLDER_ID`）。
  - 程式碼需要時一律 `sys.exit` 提示缺少哪個設定，**沒有寫死的預設值**。
- 唯一留在版控的識別碼是 Apps Script `sourceId`（`.clasp.json`）。它**不是憑證**：
  知道 ID 也必須有該 Google 帳號的授權才能讀寫，且 `clasp push` 需要它才能運作。
- 目的地的資料夾 ID 只在執行時由程式印出，不會寫進 repo。
- 執行產物（`*.log`、`*.err`、`*.pid`、`__pycache__/`）與本機設定
  （`bridge_secret.txt`、`bridge_url.txt`、`source_id.txt`）都在 `.gitignore`；
  `git status --ignored --porcelain` 可確認。
- 掃描（含完整歷史）——**注意別把真實 ID 寫進檔案**：

```bash
git grep -I -n -E "drive\.google\.com|docs\.google\.com|@gmail\.com|script\.google\.com"
git log --all -p | grep -nE "BRIDGE_SECRET *= *['\"][0-9a-f]{16,}|BRIDGE_SOURCE_ID" | head
```

## 公開化是怎麼做的（2026/10/28）

1. **輪替密鑰**：舊密鑰作廢，新的只在本機 `bridge_secret.txt` + 雲端 Script Properties。
   輪替後實測：舊密鑰 `ping` → `{"ok":false,"error":"unauthorized"}`，新密鑰 → `ok:true`。
2. **密鑰/ID 移出程式碼**：`cloneBridge.gs`、`startSmartCloneCNN.gs` 改讀
   `PropertiesService`（`BRIDGE_SECRET`、`SOURCE_FOLDER_ID`）；Python 改讀本機檔／環境變數。
3. **`bridge_url.txt` 移出版控** 並加進 `.gitignore`（`git rm --cached`）。
4. **歷史重寫**：舊 commit 仍含舊密鑰，壓成單一乾淨 commit 後 force push
   （`git checkout --orphan` → commit → `git branch -D main` → `git push -f`）。
5. 部署新版本（`clasp push -f` + `gs_deploy_webapp.py`，**網址不變**），
   用一次性 `?action=bootstrap` 寫入 Script Properties，再 `bridge_test.py` 確認 `BRIDGE_OK`。

> 為什麼「輪替」比「清歷史」重要：force push 後 GitHub 仍可能用舊 SHA 直接開舊 commit，
> 但裡面的密鑰已經作廢 → 挖到也沒用。清歷史只是減少困擾，不是唯一防線。

### 以後想再換密鑰（不用改任何程式碼）

```bash
URL=$(cat bridge_url.txt); OLD=$(cat bridge_secret.txt)
NEW=$(python3 -c 'import secrets;print(secrets.token_hex(16))')
curl -s "$URL?action=rotate&secret=$OLD&new=$NEW"   # {"ok":true,"rotated":true}
printf '%s\n' "$NEW" > bridge_secret.txt            # 本機同步更新
python3 bridge_test.py                              # BRIDGE_OK
```

`?action=bootstrap` 只在「雲端還沒有密鑰」時有效，設定過就永遠回
`already initialized`，所以不會被別人搶先初始化。

## 分享／協作

**現況**：repo 是 public，任何人都能看程式與 clone；但**沒有人能用你的備份通道**，
因為 `bridge_secret.txt`／`bridge_url.txt`／`source_id.txt` 都不在 repo 裡。

### 要讓朋友「看／改程式」

直接給網址就好，或加協作者（要讓對方能 push 才需要）：

```bash
gh api -X PUT repos/kalpakjian/cnn-smart-clone/collaborators/<朋友的GitHub帳號> -f permission=push
gh api repos/kalpakjian/cnn-smart-clone/invitations --jq '.[] | .invitee.login'
gh api -X DELETE repos/kalpakjian/cnn-smart-clone/collaborators/<帳號>   # 收回
```

### 要讓朋友「自己備份自己的 Drive」

每人各自建立自己的 Apps Script 專案與部署、自己的密鑰（見「首次設定」）。
**不要**把你的 `bridge_url.txt`／`bridge_secret.txt` 給別人：拿到的人可以
`action=sync` 同步進你的 Drive、`action=trash` 刪你備份裡「來源沒有」的檔案。

### 想收回整個通道

```bash
clasp delete-deployment <deploymentId>   # Web App 立刻失效, 本機檔案不受影響
```

> 本機 Python 呼叫 Web App 沒有帶 OAuth，靠的是 `ANYONE_ANONYMOUS` + secret，
> 所以**把 Web App 改成限制存取會讓 `clone_cnn.py` 直接失效**；
> 保護方式只能是「不要把網址與 secret 外流」。

> 這套設計是**單人用**：`clone_cnn.py` 呼叫的是「自己」的 Web App、複製進「自己」的 Drive。

## 本資料夾的工具

| 檔案 | 用途 |
|---|---|
| `clone_cnn.py` | **主入口**：觸發雲端複製 + 驗證（`--verify` / `--dry-run` 可只檢查；`--if-needed` 已一致就不觸發同步） |
| `cleanup_extra.py` | 清理備份裡「來源已刪除」的多餘檔案（預設只列出，`--trash` 才刪；`--name` 指定單一檔案） |
| `backup_cnn_drive.py` | 驗證／預覽。`--verify` 為**內容比對**（大小 + md5 + 0 byte）；備份模式會明確報錯（憑證不足，正常） |
| `diagnose_broken.py` | 唯讀診斷：空檔案／大小不符／md5 不符。`--file "檔名"` 看單檔中繼資料 |
| `bridge_url.txt` | **本機檔（不進版控）**：cloneBridge Web App 的 `/exec` 網址 |
| `bridge_secret.txt` | **本機檔（不進版控）**：cloneBridge 共享密鑰 |
| `source_id.txt` | **本機檔（不進版控）**：來源資料夾 ID |
| `cloneBridge.gs` | 雲端 Web App 橋接：`?action=ping` / `sync` / `extra`（列出多餘檔） / `trash`（刪除多餘檔）；密鑰與來源 ID 讀 Script Properties，另有 `bootstrap`（一次性初始化）與 `rotate`（換密鑰） |
| `startSmartCloneCNN.gs` | 雲端真正執行複製（含 0 byte 自我修復），已 `clasp push` 上雲 |
| `startSmartCloneCNN.gs.orig` | 第一次修改前的原始版本備份（來源 ID 已換成 `YOUR_SOURCE_FOLDER_ID` 佔位符） |
| `gs_deploy_webapp.py` | 重新部署 Web App（版本用 API、部署用 `clasp deploy -i`，網址不變），會更新 `bridge_url.txt` 並自動 ping 驗證 |
| `bridge_test.py` | 測試 Web App：`bridge_test.py [url] [secret] [action]` |
| `gs_files.py` | 列出雲端 Apps Script 檔案；`gs_files.py <檔名> <路徑>` 可 dump 內容 |
| `gs_remove_file.py` | 從雲端 Apps Script 專案移除檔案（`clasp push` 不會刪除雲端多餘檔） |
| `gs_deployments.py` | 列出部署與 entryPoints（含 Web App 網址） |
| `gs_run.py` | 用 Apps Script API 執行雲端函式（目前 NOT_FOUND，需開啟 Apps Script API） |
| `test_copy.py` | 一次性實驗：證明 `files.copy` 在目前權限下會 403 |

## 踩過的坑（重要）

- **`clasp push` 會把資料夾內所有 `.js` / `.gs` 都推上雲端**。dump 雲端程式碼請存成 `.gs.txt`；
  Node 用的 `.js` 也要改成 `.js.txt`，否則會混進 Apps Script 專案。
- **雲端專案裡有 Node 腳本會讓 Web App 整個崩潰**：`_compare_check.js` 用了 `require`，
  Web App 回 `ReferenceError: require is not defined`。已移除該檔。
- **`clasp push` 有時會說 `Skipping push.`**（快取誤判），加 `-f` 強制推送。
- **Apps Script API 的部署欄位是 `entryPoints[].webApp.entryPointConfig`**（複數、且有嵌套），
  不是 `entryPointConfig`；`entryPoints` 也是**輸出**欄位，用 clasp `deploy` 建立 Web App 部署最簡單。
- **Web App 部署會凍結在當時的版本**：改 `.gs` 後要 `clasp push -f` → `clasp deploy -d "..."` → 更新 `bridge_url.txt`。
- **`clasp run` 一律回 `NOT_FOUND`**（Apps Script API 未啟用），不要浪費時間。
- **`projects.deployments.create` 不吃 `deploymentConfig` / `entryPoints`**（HTTP 400
  `Unknown name "deploymentConfig"`）：建立／更新部署改用
  `clasp deploy -i <deploymentId> -V <版本>`。用 `-i` 更新既有部署 → **網址不變**，
  也不會殘留一堆舊部署（`gs_deploy_webapp.py` 已照這個方式改好）。
- **Web App 偶爾回 `Remote end closed connection without response`**（雲端跑太久或被限流）：
  `clone_cnn.py` 會自動跑下一輪續傳，進度保留在雲端，重跑即可；以最後的驗證結果為準。
- 讀 log 請用 `-Encoding UTF8`，並設 `$env:PYTHONIOENCODING='utf-8'`。
- PowerShell `Set-Content -Encoding UTF8` 會加 BOM，寫網址檔請用
  `[System.IO.File]::WriteAllText(..., New-Object System.Text.UTF8Encoding($false))`。
- 單一 shell 指令有 30 秒上限，掃描類指令要用 `Start-Process` 背景執行 + 輪詢。
  （`cleanup_extra.py` 的雲端掃描要 1～2 分鐘，比 `clone_cnn.py` 慢，一定要背景跑。）
- **刪除檔案不能用本機憑證**（只有 `drive.file` + `drive.metadata.readonly`，備份檔是
  Apps Script 建的，本機動不了），要走 cloneBridge 的 `action=trash`；見「清理多餘檔案」。
- Python 輸出被重導到檔案時是**區塊緩衝**，log 會等程式結束才出現；不要以為卡住了，
  用「程序是否還在」判斷，或照 `clone_cnn.py` 那樣加 `flush=True`。
- `Start-Process -ArgumentList` 傳陣列時**不會自動加引號**，含空格的參數要用單一字串並自行加 `\"`。

