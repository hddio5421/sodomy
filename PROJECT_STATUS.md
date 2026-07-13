# 台股 20 週 MA 專案狀態與維護說明

最後更新：2026-07-13

## 目前狀態

- 實際專案位置：`C:\Users\Ernesto\Documents\工作區\林恩如`
- 歷史資料起點：`2000-01-01`
- 已完成的基礎資料：2,530 檔股價與歷史股本，既有完整資料截至 `2026-07-10`
- 後續更新已改為自動日期、單一程式、每次最多 550 檔、可跨排程接續
- 固定結束日 `2026-07-10` 與程式內等待 65 分鐘的舊流程，已從排程入口移除

## 後續增量更新設計

排程入口只有一個：

```powershell
.\start_downloader.ps1
```

實際執行：

```powershell
C:\Users\Ernesto\miniconda3\python.exe src\run_downloader.py --end auto --batch-size 550 --sleep 0.15
```

流程：

1. 第一次執行建立本輪狀態，鎖定截止日與股票清單。
2. 從上一個完整週後的星期一開始請求，以便覆蓋所有尚未定稿的本週日線。
3. 按股票清單順序選取尚未到達截止日的股票，每次最多 550 檔。
4. 每成功一檔就以原子方式更新 `price_manifest.json`；排程中斷或達 API 上限後，下次會跳過已完成股票並接續。
5. 只有全部股票完成後才讀取所有股價快取，重建週 K、MA20、選股與網頁 JSON。
6. 完成後清除本輪狀態，下一次執行才會建立新的截止日。

狀態檔與互斥鎖：

- `data/raw/incremental_update_state.json`
- `data/raw/incremental_update.lock`

互斥鎖可避免工作排程器在上一輪尚未結束時重複啟動相同下載。超過 4 小時的殘留鎖會自動清除。

## 550 檔與 API 限制

- FinMind 註冊帳號目前文件列出的限制為每小時 600 次 API 請求。
- 每批最多 550 檔，預留約 50 次給股票清單或重試等額外請求。
- 約 2,530 檔需 5 次排程才完成一輪。
- 碰到上限時不在程式內睡 65 分鐘；程式保存進度後結束，交由下一次排程接續。
- 歷史股本不納入每週 API 下載批次，以免多用 2,530 次請求；重建時使用既有股本快取。

## 週中與週末更新

- 平日執行：自動截止到當天，可產生部分週資料。
- 週末執行：自動截止到剛結束的週五。
- 星期五當天不立即宣告完整週；從星期六開始才將該週五標記為 `finalized_week_through`。
- 週中下載過並不會妨礙週末更新。週末仍從該週星期一重抓所有實際交易日，覆蓋同週舊資料，再重新合併週 K。
- 若更新起點是星期二，請求仍由星期一開始。星期一若休市，只會沒有星期一資料；當週第一個實際交易日自然成為週 K 開盤日。
- 若週末忘記執行，下次排程會繼續補抓；在完成前，網頁仍保留上一個「全市場一致完成」的輸出。

## MA20 正確性

日線快取會合併去重，當週範圍採覆蓋方式；所有股票到齊後，程式從完整歷史日線重新建立全部週 K，再計算 rolling 20 週 MA。因此：

- 週中看到的 MA20 或突破訊號屬於暫時結果。
- 週末完整資料會取代部分週並重新計算。
- 不會只拿新增一週單獨計算 MA20，也不會失去前 19 週資料。

網頁 `chart_index.json` 新增：

- `data_through`：資料實際抓取截止日
- `finalized_week_through`：最後一個確認完整的週五

網頁頁首會依這兩個欄位顯示完整週或部分週提示。

## GitHub 與排程

- 拆成 550 檔主要解決 FinMind 每小時限制與中斷續傳，不會減少整體運算時間。
- 公開儲存庫使用標準 GitHub-hosted runner 不計 Actions 分鐘；私人 GitHub Free 帳號有每月 Actions 分鐘額度。
- 已新增 `.github/workflows/finmind-weekly-update.yml`，使用 Repository Secret `FINMIND_TOKEN`，不需要也不會上傳 `.env`。
- GitHub-hosted runner 是臨時環境，因此工作流程使用 `actions/cache` 保存與還原 `data/raw`、manifest 和輪次狀態。
- Cache key 每次執行都不同，下一次透過共同 prefix 還原最近一份快取，避免不可變 cache key 無法覆寫。
- 第一次沒有 cache 時會從 `2000-01-01` 分五批建立完整股價基礎；之後才使用當週覆蓋更新。
- 歷史股本使用已追蹤的 `data/processed/capital_history.csv`，GitHub 排程不會每週呼叫股本 API。
- 台灣時間每週六 10:00 至 14:00 每小時執行一次。全部完成後，Actions bot 才 commit、push `chart_index.json`、`series/`、`signals/` 與股本快取。
- `.gitignore` 已忽略 `data/raw/`、大份 CSV、log 與 `.env`，避免把 token、本機狀態或大量原始資料提交到 GitHub。

GitHub 儲存庫必須先設定：

1. `Settings` → `Secrets and variables` → `Actions` → 新增 `FINMIND_TOKEN`。
2. `Settings` → `Actions` → `General` → 確認 workflow 允許讀寫 repository contents。
3. 首次可到 `Actions` → `FinMind weekly update` 手動執行；後續由週六排程接續。

## 操作指令

查看接續狀態：

```powershell
C:\Users\Ernesto\miniconda3\python.exe src\run_downloader.py --status
```

預覽下一批，不連線也不修改狀態：

```powershell
C:\Users\Ernesto\miniconda3\python.exe src\run_downloader.py --dry-run
```

排程實際執行：

```powershell
.\start_downloader.ps1
```

下載日誌：`logs/finmind_downloader.log`

本機網頁：`http://127.0.0.1:8358/web/`

## 主要檔案

- `src/pipeline.py`：下載、快取合併、週 K、MA20、選股與網頁輸出
- `src/run_downloader.py`：550 檔分批、狀態接續、當週覆蓋、完成後重建
- `start_downloader.ps1`：唯一的排程啟動入口
- `data/raw/price_manifest.json`：每檔股價涵蓋截止日
- `data/raw/incremental_update_state.json`：目前輪次與接續狀態
- `data/processed/chart_index.json`：網頁索引與資料完整度欄位
- `web/app.js`：網頁操作與資料完整度顯示
- `.github/workflows/finmind-weekly-update.yml`：GitHub Secret、五次週六排程、cache 接續與完成後自動提交

## Git 操作狀態

本次只修改本機工作樹，尚未自動 commit、push 或部署。要讓 GitHub 排程生效，必須將本次程式、workflow 與 `data/processed/capital_history.csv` 一起提交到 GitHub。
