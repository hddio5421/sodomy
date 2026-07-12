# 台股 20 週 MA 選股與週 K 檢視

這個專案會從 FinMind 下載台股日線資料，轉成週 K，找出「本週收盤價剛站上 20 週均線」的股票，並輸出本機網頁可讀的圖表資料。

目前完整資料區間：`2000-01-01` 到 `2026-07-10`。

截至 `2026-07-11`，2,530 檔股票的股價與歷史股本皆已下載完成，網頁資料也已重建。

## 啟動自動續抓

```powershell
.\start_downloader.ps1
```

它會持續執行：

1. 下載尚未完成的股票資料。
2. 如果碰到 FinMind API 請求上限，就等待 65 分鐘。
3. 等待後自動繼續抓。
4. 每次碰到上限或完成一輪時，都會用目前快取重建網頁資料。

log 位置：

```text
logs/finmind_downloader.log
```

## 手動執行

```powershell
python src/pipeline.py --start 2000-01-01 --end 2026-07-10
```

只用本機快取重建網頁：

```powershell
python src/pipeline.py --start 2000-01-01 --end 2026-07-10 --cached-only --sleep 0
```

## 查看網頁

```text
http://127.0.0.1:8358/web/
```

## 選股條件

```text
本週 close > 本週 MA20
且
上週 close <= 上週 MA20
```

週 K 由日線自行彙總：開盤為當週第一個交易日，最高/最低為當週極值，收盤為當週最後一個交易日，成交量為當週加總。
