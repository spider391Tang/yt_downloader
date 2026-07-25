# YouTube MP4／MP3 命令列下載器

輸入單支公開 YouTube 影片連結，下載為 MP4 或轉換成 MP3。支援一般影片、
Shorts 與已結束的直播；不支援播放清單、進行中的直播或需要登入的內容。

> 請只下載你擁有權利或已取得授權的內容，並遵守 YouTube 服務條款及所在地法律。

程式元件、資料路徑與 Mermaid 圖表請參考
[ARCHITECTURE.md](ARCHITECTURE.md)。

## 系統需求

- Windows 10／11
- Python 3.10 以上
- FFmpeg 與 FFprobe，兩者都需加入 `PATH`
- Node.js 22 以上或近期 Deno，供 yt-dlp 完整解析 YouTube

確認外部工具：

```powershell
py --version
ffmpeg -version
ffprobe -version
node --version
```

## 安裝

在專案資料夾開啟 PowerShell：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果系統尚未安裝 FFmpeg 或 Node.js，可使用 Chocolatey：

```powershell
choco install ffmpeg
choco install nodejs-lts
```

安裝後重新開啟 PowerShell，讓新的 `PATH` 生效。

## 使用方式

下載最高 1080p MP4：

```powershell
.\.venv\Scripts\python.exe app.py "https://www.youtube.com/watch?v=VIDEO_ID" --format mp4
```

下載 720p MP4：

```powershell
.\.venv\Scripts\python.exe app.py "YOUTUBE_URL" --format mp4 --quality 720
```

下載來源提供的最高畫質 MP4：

```powershell
.\.venv\Scripts\python.exe app.py "YOUTUBE_URL" --format mp4 --quality best
```

轉換為 192 kbps MP3，並加入來源提供的基本 metadata：

```powershell
.\.venv\Scripts\python.exe app.py "YOUTUBE_URL" --format mp3
```

指定輸出資料夾：

```powershell
.\.venv\Scripts\python.exe app.py "YOUTUBE_URL" --format mp3 --output-dir "D:\Music"
```

若公司網路使用 HTTPS 攔截，且 Python 無法信任公司的內部 CA，可明確停用
本次下載的憑證驗證：

```powershell
.\.venv\Scripts\python.exe app.py "YOUTUBE_URL" --format mp3 --no-check-certificates
```

此選項會顯示安全警告。它會讓程式無法驗證遠端伺服器身分，只應在你信任的
公司網路中使用；不要在公共 Wi-Fi 或不受信任的網路使用。

也可以不帶參數啟動，再依提示貼上網址並選擇格式：

```powershell
.\.venv\Scripts\python.exe app.py
```

預設檔案會放在 `downloads`，命名為：

```text
影片標題 [YouTube ID].mp4
影片標題 [YouTube ID].mp3
```

同一檔案已存在時會直接跳過，不會覆寫。中途取消時 `.part` 檔案會保留，
再次執行相同命令可由 yt-dlp 嘗試續傳。

## 退出碼

| 退出碼 | 意義 |
|---:|---|
| `0` | 下載成功，或檔案已存在而跳過 |
| `1` | 下載、網路、合併或轉檔失敗 |
| `2` | 參數錯誤或缺少必要環境 |
| `130` | 使用者按下 `Ctrl+C` 取消 |

## 測試

測試不會連線到 YouTube，也不會下載真實媒體：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

端對端測試請選擇你有權下載的短影片，分別執行 MP4 與 MP3 命令，再用
`ffprobe` 確認輸出：

```powershell
ffprobe "downloads\檔案名稱.mp4"
ffprobe "downloads\檔案名稱.mp3"
```

## 疑難排解

YouTube 會不定期調整網站行為。若原本可用的公開影片突然無法下載，先更新
yt-dlp：

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade "yt-dlp[default]"
```

若顯示找不到 FFmpeg，請確認 `ffmpeg -version` 與 `ffprobe -version` 都能在
同一個 PowerShell 視窗執行。需要登入、會員限定、私人、年齡限制或地區限制的
內容不在第一版支援範圍。

如果錯誤包含 `CERTIFICATE_VERIFY_FAILED`，優先請 IT 提供公司 CA 憑證並加入
Python 信任設定。`--no-check-certificates` 僅作為無法立即設定 CA 時的繞過方式。
