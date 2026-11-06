# Aqua Planet · KOL Partner Studio

菲律賓克拉克 Aqua Planet 的推薦碼與導流成效管理網站。前台為品牌連結頁；後台建立 KOL 專屬連結、管理狀態、檢視流量與匯出 CSV。Python 3.12 以上；本機可使用標準函式庫與 SQLite，Vercel 使用外部 PostgreSQL 永久保存資料。

## Vercel 部署（目前選用的上線方式）

已提供 `api/index.py`、`vercel.json`、`.python-version` 與固定版本的 `requirements.txt`。Vercel 使用 Python Function 處理前後台與轉址；帳號、推薦碼、工作階段、登入節流及點擊事件全部存於外部 PostgreSQL。**不能使用 `/tmp` SQLite 取代雲端資料庫**；缺少資料庫設定時服務回應 503，避免顯示不可靠或會消失的統計。

1. 使用既有 Vercel 帳號登入（Google 登入也可以）。在 **Create New → Project** 匯入 GitHub 的 `hugohuhuhu/KOL-tracker`；若尚未授權 GitHub，在匯入頁連接即可。部署的分支必須包含此份 `vercel.json`，Framework 選 **Other**，Root Directory 使用儲存庫根目錄，不需自訂 Build Command 或 Output Directory。
2. 在 Vercel 的 Storage／Marketplace 建立並連接 **Neon PostgreSQL**，或連接你已有的 PostgreSQL。資料庫與 Function 選相近區域。Vercel 需取得 `DATABASE_URL` 或 `POSTGRES_URL`（若整合使用其他變數名稱，在 Vercel 私密環境變數中指定其中一個）。建議使用整合提供的 pooled 連線網址。
3. 在專案的 **Settings → Environment Variables** 設定 `ADMIN_USERNAME` 與至少 12 字元的 `ADMIN_PASSWORD`，填入自選帳密。僅輸入 Vercel 的私密欄位，不能貼到聊天、GitHub 或程式碼。Vercel 版本 Cookie 強制使用 Secure；首次帳號建立後，可移除這兩個初始化變數，不會刪除既有帳號。
4. 將資料庫與管理員變數套用到 **Production**；若使用 Preview 部署測試，需為 Preview 配置獨立測試資料庫與管理員，避免預覽流量污染正式數據。最後 **Redeploy**，等待完成。資料表會在第一次 Function 請求時安全建立，重啟不覆寫既有資料。
5. 開啟 Vercel 產生的 HTTPS 網址。`/health` 應回傳 `{"status":"ok"}`；前台在 `/`，後台在 `/admin`。登入後於「頁面與連結」設定正式公開 HTTPS 網址，再建立並分發 KOL 連結。
6. 用另一個瀏覽器開啟第一個推薦連結並點擊 KKday／Klook，確認後台增加造訪與平台點擊。重新部署後確認推薦碼與數據仍存在，再開始正式營運。

雲端資料庫連線強制驗證 TLS 憑證。請使用平台提供的正式 PostgreSQL 網址。程式不會記錄資料庫連線字串或密碼。原有 SQLite 檔案不會自動遷移至 PostgreSQL；如果已累積真實資料，先另外遷移與驗證，不能直接切換資料庫當作已完成搬移。備份與資料保留請在資料庫平台設定。

目前儲存庫提供部署設定，不代表 Vercel 專案或 Neon 資料庫已開通。首次連接第三方帳號需要帳號擁有者在平台完成授權。Vercel 與資料庫方案、費用及使用條件以各平台當前資訊為準。

## 啟動

```sh
cd /workspace/KOL-tracker
python3 app.py
```

服務預設監聽 `127.0.0.1:8000`。前台路徑 `/`，管理中心 `/admin`。首次從本機開啟後台時，建立管理員帳號與至少 12 字元的密碼；不提供預設帳密，也不開放額外帳號註冊。

如需從遠端使用，**先在伺服器上建立管理員**：

```sh
python3 app.py --create-admin
```

此指令互動輸入帳號及密碼，不把密碼放入指令參數或紀錄。接著可執行 `python3 app.py --host 0.0.0.0 --port 8000`，透過 HTTPS 反向代理提供服務。正式部署應設定 `COOKIE_SECURE=1`、使用可持久保存且有備份的 `DATABASE_PATH`，並於後台「頁面與連結」設定正式 HTTPS 網域。Python 內建 HTTP server 適合開發／小規模內部驗證；公開正式服務前應使用受管理的反向代理、存取限制及流量限制，並安排運作監控。

## 使用流程

1. 後台「頁面與連結」確認五個目的地。已預填使用者提供的 FB、IG、官方網站、KKday、Klook 網址。FB 目前是搜尋結果連結，後台有提醒改為粉絲專頁直連。
2. 新增 KOL 名稱與渠道，推薦碼可自訂或自動產生。複製形如 `/r/AP-ABC12345` 的完整推薦連結給 KOL。
3. 訪客開啟 `/r/<推薦碼>`，記錄一次造訪後轉至 `/p/<推薦碼>` 品牌頁。
4. 訪客點擊平台按鈕，透過 `/go/<推薦碼>/<平台>` 記錄一次平台點擊，再轉至設定中的原始網址；不會移除合作或聯盟參數。
5. 後台查看最近 7／30／90 天或全部資料，依造訪排序，匯出各 KOL 與五個目的地的 CSV。搜尋與狀態篩選只影響管理清單，CSV 匯出目前期間的全部 KOL。
6. 停用推薦碼將阻擋新的造訪與轉址，歷史資料保留；可重新啟用。

## 統計定義

- **造訪次數**：有效 `/r/` GET 請求。重複開啟會累計；重新整理品牌頁 `/p/` 不增加造訪。
- **不重複訪客**：匿名第一方 Cookie（保留一年）識別同一瀏覽器；資料庫僅存其 SHA-256 雜湊。每位 KOL 個別去重；總覽跨 KOL 去重，所以各 KOL 不重複訪客相加可能大於總覽。
- **平台點擊**：有效 `/go/` GET 請求，重複點擊會累計；未經推薦碼的首頁點擊不算入 KOL 成效。訪客直接分享 `/p/` 頁面可能造成平台點擊多於推薦連結造訪，這不是訂單轉換率。
- 統計日期採台北時間 UTC+8；「最近 7 天」包含今天和前 6 個曆日。
- 排除常見 bot／crawler／社群預覽 User-Agent。這是基本請求統計，無法完全排除機器人、連結預取、自行刷量或跨裝置重複，不能作為經稽核的廣告歸因。
- 無訂單回傳串接，**不追蹤成交、營收或 KKday／Klook 購買轉換**。需另取得平台的聯盟／訂單 API 或回傳機制。
- 不記錄 IP、完整 User-Agent 或完整 HTTP 存取紀錄；管理員需依實際地區、Cookie 使用及資料保存要求提供適當告知。停用不刪除歷史數據，資料保留政策應由營運方決定。

## 持久化與設定

| 設定 | 預設／用途 |
| --- | --- |
| `DATABASE_PATH` | `data/aqua.sqlite3`，包含管理員雜湊、工作階段、設定、KOL 與事件 |
| `DATABASE_URL` / `POSTGRES_URL` | Vercel 必填其一；PostgreSQL 私密連線網址，優先使用 `DATABASE_URL` |
| `HOST` | `127.0.0.1` |
| `PORT` | `8000` |
| `COOKIE_SECURE` | 正式 HTTPS 部署設為 `1` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 選填，從託管平台的私密變數建立首次管理員；密碼至少 12 字元。已有管理員時不覆寫，不能用來重設密碼 |

`data/` 已加入 Git 忽略，不能提交資料庫或密碼。安裝／重啟不覆寫既有管理員、設定或事件。SQLite 使用 WAL；備份運行中的資料庫請使用 SQLite backup API，不能只複製主檔而漏掉 WAL。管理工作階段 12 小時過期，具 HttpOnly／SameSite Cookie、CSRF 驗證、PBKDF2 密碼雜湊。登入節流存於資料庫，跨重啟／Function 執行個體共用；反向代理仍應設定外層流量限制，不要信任任意代理標頭。登入節流只保存來源識別的雜湊，不存原始 IP。

## 驗證

```sh
python3 -m unittest discover -s tests -v
node --check static/admin.js
node --check static/landing.js
```

整合測試使用暫存資料庫和本機隨機埠，不呼叫預訂平台、不修改正式資料。涵蓋登入／CSRF／登出、推薦碼狀態、Cookie 去重、跨 KOL 歸因、平台轉址、CSV 公式防護、日期邊界及設定持久化。健康檢查為 `GET /health`。

環境若已提供 Python Playwright 與 `/usr/bin/chromium`，可選擇執行 `python3 tests/browser_smoke.py` 驗證實際桌面／手機操作。此測試使用隔離的測試資料庫，對外預訂網址會被攔截，不建立訂單。截圖輸出到已忽略的 `test-results/`，畫面數字屬測試資料。

PostgreSQL 與 Vercel 入口的整合驗證（需要本機 Docker）：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tests/postgres_smoke.py
```

測試會使用官方 `postgres:16-alpine` 容器、隨機埠與獨立 schema，執行完整 HTTP 測試及 Function 冷啟動／跨實例工作階段／登入節流驗證；完成後清除自己的容器。只有這個明確允許的 loopback 測試使用非 TLS 連線；正式遠端連線仍驗證 TLS。`python3 -m unittest discover -s tests -v` 另驗證未配置 Vercel 資料庫時安全回應 503、不開放公開註冊及 Secure Cookie。

## 替代方案：Railway + 持久磁碟

已附 `Dockerfile` 和 `railway.json`，使用單一執行個體與健康檢查。Railway 屬付費用量型服務，實際方案及價格請以平台當前資訊為準；建立服務前先確認費用並設定平台支出提醒。

1. 將這份程式碼存入 GitHub 儲存庫後，在 Railway 建立專案，選擇從 GitHub 儲存庫部署，指定包含程式碼的分支。
2. 為這個服務新增 **Volume**，掛載路徑必須是 **`/data`**。這一步是必要的，否則重新部署後可能遺失推薦碼、管理員及點擊紀錄。
3. 在服務的 **Variables** 設定 `ADMIN_USERNAME`（自選帳號）、`ADMIN_PASSWORD`（自選至少 12 字元的強密碼）、`COOKIE_SECURE=1`。密碼僅輸入 Railway 私密變數，不放入 GitHub、聊天或程式碼。`DATABASE_PATH=/data/aqua.sqlite3` 和 `HOST=0.0.0.0` 已在 Dockerfile 設定；`PORT` 由 Railway 提供。
4. 重新部署並確認服務健康後，在服務的 Networking 設定產生公開網域（不必先購買網域）。Railway 提供 HTTPS。
5. 開啟該網域的 `/admin`，以剛設定的帳密登入。在「頁面與連結」填入完整公開 HTTPS 網址並儲存。
6. 建立第一個 KOL 推薦碼，複製推薦連結，在另一個瀏覽器開啟並點擊平台按鈕，確認後台增加造訪與平台點擊，才開始分發連結。
7. 將平台 Volume 納入備份計畫。此版本使用 SQLite，維持單一副本；不要移除或替換 Volume。正式開放前請依上方部署說明完成代理、流量限制及營運檢查。

首次管理員建立後，從 Variables 移除 `ADMIN_PASSWORD` 和 `ADMIN_USERNAME` 並重新部署，帳號仍由持久磁碟保存。請用密碼管理器保留帳密。目前沒有電子郵件重設密碼功能；不要藉由刪除資料庫來重設，這會刪除成效資料。

每個雲端任務本身已隔離，請沿用現有 checkout；除非使用者明確要求，不建立 Git worktree。發布環境快照不等於將網站部署到公網，正式網址與託管服務仍需另行配置。
