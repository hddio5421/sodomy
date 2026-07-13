# 台股 20 週 MA 選股與週 K 檢視

本專案從 FinMind 下載台股日線，合併成週 K，計算 20 週均線，並產生可由網頁讀取的選股與個股圖表資料。

目前歷史資料起點為 `2000-01-01`；後續更新的結束日由程式依執行日期自動決定，不再需要每週修改固定日期。

## 排程用增量下載

```powershell
.\start_downloader.ps1
```

每次執行只處理一批，規則如下：

1. 每次最多向 FinMind 下載 550 檔股價，低於註冊帳號每小時 600 次請求限制並保留餘裕。
2. 下載進度保存在 `data/raw/incremental_update_state.json`；下次執行會自動從未完成的股票接續，不必建立多支程式。
3. 同一輪會鎖定相同截止日，避免不同批次混用不同日期。
4. 週中執行時，資料可暫時包含尚未結束的部分週 K。
5. 後續再執行時，會從上一個完整週之後的週一重新抓取並覆蓋當週資料；因此週末執行後會用完整交易週重新合併週 K、MA20 與突破訊號。
6. 只有全部股票都到達該輪截止日後，才會從完整快取重建週 K、MA20、選股與網頁 JSON；不會用只完成 550 檔的混合資料發布結果。
7. 歷史股本不在每週更新中重抓，重建時直接使用既有快取。

約 2,530 檔股票需要 5 次排程完成一輪。建議排程每小時執行一次；若忘記週末執行，下一次排程仍會補抓並覆蓋尚未定稿的當週資料。

查看進度（不連 FinMind）：

```powershell
C:\Users\Ernesto\miniconda3\python.exe src\run_downloader.py --status
```

預覽下一批（不寫入、不下載）：

```powershell
C:\Users\Ernesto\miniconda3\python.exe src\run_downloader.py --dry-run
```

日誌位置：`logs/finmind_downloader.log`。

## 日期與週 K 規則

- 平日自動抓到執行當日；週六、週日自動抓到剛結束的週五。
- 星期五當天仍標示為未定稿週，週六起才視為完整週，避免收盤資料尚未完整上架。
- 起始更新日即使是星期二，也會從該週星期一開始請求；若星期一休市，FinMind 只會回傳實際交易日，不影響週 K。
- 週 K 的開盤、最高、最低、收盤、成交量分別使用該週第一筆、最高、最低、最後一筆與合計成交量。
- MA20 每次由完整歷史週 K 重新計算，因此覆蓋當週日線後不會斷掉前 20 週的計算基礎。

## 網頁

本機網址：`http://127.0.0.1:8358/web/`

頁首會顯示「資料截至」與「完整週截至」。若週中更新，會明確標示當週尚未完成。

選股條件：

```text
本週 close > 本週 MA20
且
上週 close <= 上週 MA20
```

## GitHub Actions 全自動執行

工作流程位於 `.github/workflows/finmind-weekly-update.yml`，不會把 `.env` 上傳到 GitHub。請先在儲存庫設定：

1. `Settings` → `Secrets and variables` → `Actions`。
2. 建立 Repository secret，名稱必須是 `FINMIND_TOKEN`，值為 FinMind Token。
3. 到 `Settings` → `Actions` → `General` → `Workflow permissions`，確認 Actions 可以使用讀寫權限；工作流程本身也已宣告 `contents: write`。

排程為台灣時間每週六 `10:00` 至 `14:00`，每小時一次，共五次。每次執行會：

1. 從 GitHub Actions Cache 還原 `data/raw`、manifest 與接續狀態。
2. 執行一批最多 550 檔。
3. 將更新後的 `data/raw` 以新 cache key 保存，供下一小時接續。
4. 全部股票完成後才重建網頁資料，並由 `github-actions[bot]` commit、push 回執行工作流程的分支。

第一次尚無 Actions Cache 時，程式會自動從 `2000-01-01` 建立完整股價基礎；不是只抓當週。歷史股本改由 Git 內的 `data/processed/capital_history.csv` 提供，不會在 GitHub 首次執行時額外重抓 2,530 檔股本。

也可以在 GitHub 的 `Actions` → `FinMind weekly update` → `Run workflow` 手動補跑。若某週五次仍有失敗股票，手動再執行一次即可依 cache 接續。

注意：550 檔分批主要處理 FinMind 每小時限制與中斷續傳，不會減少總運算時間；Actions Cache 是 GitHub-hosted runner 能跨次接續的必要條件。
