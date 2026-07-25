# YouTube MP4／MP3 下載器：程式與架構說明

本文件說明此 Python 命令列程式的元件責任、類別關係、資料流程、媒體資料路徑
及下載時序。使用方式與安裝步驟請參考 [README.md](README.md)。

## 1. 程式目標

程式接收單支 YouTube 內容網址，透過 `yt-dlp` 取得媒體串流，再由 FFmpeg
輸出為：

- MP4：最高 720p、1080p，或來源最佳畫質。
- MP3：最佳可用音訊轉為約 192 kbps，並寫入標題、作者與日期 metadata。

第一版支援一般影片、Shorts 與已結束的直播；不支援播放清單、登入內容及
進行中的直播。

## 2. 專案結構

```text
yt_downloader/
├── app.py                  # CLI、互動輸入、訊息與退出碼
├── downloader.py           # 驗證、yt-dlp、進度、FFmpeg 與錯誤分類
├── requirements.txt        # Python 套件版本範圍
├── README.md               # 安裝與使用說明
├── ARCHITECTURE.md         # 本架構文件
├── downloads/              # 預設輸出資料夾，不納入版控
└── tests/
    ├── test_app.py         # CLI 與退出碼測試
    └── test_downloader.py  # URL、選項、下載服務與錯誤測試
```

主要責任如下：

| 元件 | 責任 |
|---|---|
| `app.py` | 解析 CLI、補足互動輸入、顯示安全警告、呼叫下載服務、回傳退出碼 |
| `downloader.py` | 驗證 YouTube URL、檢查環境、建立 yt-dlp 選項、回報進度、解析結果 |
| `yt-dlp` | 解析 YouTube metadata、選擇媒體格式、下載及續傳 |
| Node.js／Deno | 執行 YouTube JavaScript challenge；優先使用 Deno，否則使用 Node.js |
| FFmpeg／FFprobe | 合併 MP4 串流、轉換 MP3、寫入 metadata，以及人工驗證輸出 |
| `downloads/` | 保存 `.part` 暫存檔及最後的 MP4／MP3 |

## 3. 整體架構

```mermaid
flowchart LR
    User["使用者<br/>PowerShell"] --> CLI["app.py<br/>CLI / Interactive Input"]
    CLI --> Env["環境檢查<br/>yt-dlp / FFmpeg / FFprobe / JS Runtime"]
    CLI --> Service["downloader.py<br/>Download Service"]
    Service --> Validator["URL 與內容範圍驗證"]
    Service --> Config["yt-dlp Options Builder"]
    Config --> YTDLP["yt-dlp"]
    YTDLP --> JS["Node.js 或 Deno<br/>JavaScript Challenge"]
    YTDLP --> YouTube["YouTube HTTPS / Media CDN"]
    YTDLP --> FFmpeg["FFmpeg Post-processing"]
    YTDLP --> Hooks["Progress / Postprocessor Hooks"]
    Hooks --> CLI
    YTDLP --> Temp["downloads/*.part"]
    Temp --> FFmpeg
    FFmpeg --> Output["downloads/<br/>標題 [Video ID].mp4 或 .mp3"]
    Output --> CLI
    CLI --> User
```

設計重點：

- CLI 與下載核心分離，下載邏輯可在不啟動終端機的情況下單元測試。
- App 直接使用 yt-dlp Python API，不解析容易改變的一般 stdout。
- 下載進度與後製狀態只透過 hook 傳回 CLI。
- 檔名包含 YouTube ID，降低不同影片同名造成的碰撞。
- `overwrites=False` 保護現有檔案；`.part` 保留供下次續傳。

## 4. Class diagram

`app.py` 與 `downloader.py` 以函式為主，因此圖中使用 `module` 表示模組公開責任，
並列出實際存在的資料類別、例外類別與 hook 類別。

```mermaid
classDiagram
    class AppModule {
        <<module>>
        +build_parser() ArgumentParser
        +resolve_inputs(args) tuple
        +run(argv) int
        +main() int
    }

    class ArgparseParser {
        <<external>>
    }

    class ArgumentParser {
        +error(message)
    }

    class UsageError {
        <<exception>>
    }

    class DownloaderModule {
        <<module>>
        +validate_youtube_url(url) str
        +check_environment() list
        +build_ydl_options(...) dict
        +download_youtube(...) DownloadResult
    }

    class AppConfigurationError {
        <<exception>>
    }

    class DownloadFailure {
        <<exception>>
    }

    class DownloadResult {
        +Path path
        +str title
        +bool skipped
    }

    class ProgressReporter {
        +TextIO stream
        +str title
        +bool download_started
        +announce(info)
        +filter(info, incomplete)
        +progress_hook(data)
        +postprocessor_hook(data)
    }

    class YTDLPLogger {
        +str last_error
        +debug(message)
        +warning(message)
        +error(message)
    }

    class YoutubeDL {
        <<external>>
        +extract_info(url, download)
        +prepare_filename(info)
    }

    ArgparseParser <|-- ArgumentParser
    AppModule ..> ArgumentParser : 建立
    AppModule ..> UsageError : 處理
    AppModule ..> DownloaderModule : 呼叫
    AppModule ..> DownloadResult : 顯示
    DownloaderModule ..> AppConfigurationError : 拋出
    DownloaderModule ..> DownloadFailure : 拋出
    DownloaderModule ..> ProgressReporter : 建立
    DownloaderModule ..> YTDLPLogger : 建立
    DownloaderModule ..> YoutubeDL : 設定與呼叫
    DownloaderModule --> DownloadResult : 回傳
    YoutubeDL --> ProgressReporter : hooks
    YoutubeDL --> YTDLPLogger : logs
```

## 5. Data flow

以下描述資料在各處理階段的內容，而非媒體檔案實際存放位置。

```mermaid
flowchart TD
    A["CLI 原始輸入<br/>URL / format / quality / output-dir"] --> B["argparse Namespace"]
    B --> C["resolve_inputs()<br/>補足互動輸入與預設 1080p"]
    C --> D["標準化下載請求"]
    D --> E{"validate_youtube_url()"}
    E -->|無效或播放清單| F["AppConfigurationError<br/>退出碼 2"]
    E -->|合法單支內容| G["build_ydl_options()"]

    G --> H["格式選擇器<br/>MP4 video+audio 或 MP3 bestaudio"]
    G --> I["輸出策略<br/>不覆寫 / 可續傳 / Windows 安全檔名"]
    G --> J["安全與 runtime<br/>TLS 驗證設定 / Node 或 Deno"]
    H --> K["YoutubeDL.extract_info(download=True)"]
    I --> K
    J --> K

    K --> L["影片資訊<br/>title / id / ext / live_status"]
    K --> M["進度資料<br/>bytes / total / speed / ETA"]
    K --> N["下載及後製結果"]

    L --> O{"是否進行中直播"}
    O -->|是| P["DownloadFailure<br/>退出碼 1"]
    O -->|否| Q["_expected_output_path()"]
    M --> R["ProgressReporter<br/>終端進度"]
    N --> Q

    Q --> S{"最終檔案存在？"}
    S -->|否| P
    S -->|是且未下載| T["DownloadResult skipped=true"]
    S -->|是且有下載| U["DownloadResult skipped=false"]
    T --> V["CLI 顯示已跳過<br/>退出碼 0"]
    U --> W["CLI 顯示完成路徑<br/>退出碼 0"]
```

### 主要輸入資料

| 欄位 | 來源 | 規則 |
|---|---|---|
| `url` | 位置參數或互動輸入 | 必須是 YouTube 單支影片、Shorts 或直播重播 |
| `output_format` | `--format` 或互動輸入 | `mp4` 或 `mp3` |
| `quality` | `--quality` | MP4 可用 `720`、`1080`、`best`；預設 `1080` |
| `output_dir` | `--output-dir` | 預設為專案下的 `downloads` |
| `no_check_certificates` | `--no-check-certificates` | 預設 `false`；啟用時停止驗證 HTTPS 憑證 |

## 6. Data path

媒體資料不會載入為一個完整的 Python bytes 物件。yt-dlp 將網路串流直接寫入
磁碟，FFmpeg 再讀取暫存媒體並輸出最後檔案。

```mermaid
flowchart LR
    URL["YouTube URL"] --> API["YouTube Web / API"]
    API --> Metadata["Metadata<br/>title / id / formats"]
    Metadata --> Selector{"輸出格式"}

    Selector -->|MP4| Video["Video stream<br/>最高 720 / 1080 / best"]
    Selector -->|MP4| AudioM4A["M4A audio stream"]
    Selector -->|MP3| BestAudio["Best available audio stream"]

    Video --> PartVideo["downloads/*.part<br/>video temporary file"]
    AudioM4A --> PartAudio["downloads/*.part<br/>audio temporary file"]
    BestAudio --> PartSource["downloads/*.part<br/>audio source"]

    PartVideo --> Merge["FFmpeg merge"]
    PartAudio --> Merge
    PartSource --> Convert["FFmpegExtractAudio<br/>MP3 192 kbps"]
    Convert --> Tags["FFmpegMetadata<br/>title / artist / date"]

    Merge --> MP4["downloads/<br/>標題 [Video ID].mp4"]
    Tags --> MP3["downloads/<br/>標題 [Video ID].mp3"]
```

路徑規則：

1. 預設根目錄為 `<project>/downloads`，可由 `--output-dir` 覆寫。
2. yt-dlp 輸出模板為 `%(title)s [%(id)s].%(ext)s`。
3. Windows 不允許的檔名字元由 yt-dlp 處理，Unicode 中文仍會保留。
4. 下載中斷時保留 `.part`；成功後由 yt-dlp／FFmpeg 產生最終副檔名。
5. 最終路徑透過 `YoutubeDL.prepare_filename()` 計算，不從 console 文字解析。

## 7. Sequence diagram

```mermaid
sequenceDiagram
    actor User as 使用者
    participant CLI as app.py
    participant DL as downloader.py
    participant YD as yt-dlp
    participant JS as Node.js / Deno
    participant YT as YouTube
    participant FS as File System
    participant FF as FFmpeg

    User->>CLI: app.py URL --format mp3/mp4
    CLI->>CLI: parse_args() / resolve_inputs()
    CLI->>DL: check_environment()
    DL-->>CLI: warnings 或 AppConfigurationError

    opt 使用 --no-check-certificates
        CLI-->>User: 顯示 HTTPS 安全警告
    end

    CLI->>DL: download_youtube(request)
    DL->>DL: validate_youtube_url()
    DL->>DL: build_ydl_options()
    DL->>YD: extract_info(URL, download=true)
    YD->>YT: 取得網頁與 metadata
    opt YouTube JavaScript challenge
        YD->>JS: 執行 challenge
        JS-->>YD: signature / token
    end
    YT-->>YD: formats / title / video ID
    YD-->>DL: match_filter(info)

    alt 進行中的直播
        DL-->>CLI: DownloadFailure
        CLI-->>User: 錯誤訊息，退出碼 1
    else 支援的單支內容
        alt 最終檔案已存在
            YD->>FS: 檢查輸出路徑
            FS-->>YD: exists
            YD-->>DL: info，不重新下載
            DL-->>CLI: DownloadResult(skipped=true)
            CLI-->>User: 已存在、已跳過，退出碼 0
        else 需要下載
            YD->>YT: 請求媒體串流
            YT-->>YD: media bytes
            loop 下載進度
                YD-->>DL: progress_hook(bytes, speed, ETA)
                DL-->>CLI: 格式化進度
                CLI-->>User: 百分比、速度、剩餘時間
            end
            YD->>FS: 寫入或續傳 .part

            alt MP4
                YD->>FF: 合併 video + audio
                FF->>FS: 寫入最終 MP4
            else MP3
                YD->>FF: 轉換為 192 kbps MP3
                YD->>FF: 寫入 metadata
                FF->>FS: 寫入最終 MP3
            end

            FS-->>DL: 最終檔案存在
            DL-->>CLI: DownloadResult(path, skipped=false)
            CLI-->>User: 完成與絕對路徑，退出碼 0
        end
    end
```

## 8. 錯誤與退出碼架構

```mermaid
flowchart LR
    Error["原始錯誤"] --> Kind{"錯誤來源"}
    Kind -->|CLI / URL / dependency| Config["UsageError 或<br/>AppConfigurationError"]
    Kind -->|yt-dlp / network / FFmpeg| Download["DownloadFailure"]
    Kind -->|Ctrl+C| Cancel["KeyboardInterrupt"]

    Config --> E2["退出碼 2"]
    Download --> Friendly["_friendly_download_error()<br/>登入 / 地區 / 網路 / FFmpeg"]
    Friendly --> E1["退出碼 1"]
    Cancel --> E130["保留 .part<br/>退出碼 130"]
    Success["成功或已存在"] --> E0["退出碼 0"]
```

`YTDLPLogger` 保存 yt-dlp 的最後錯誤，再交由 `_friendly_download_error()` 分類。
這能讓使用者看到較清楚的中文訊息，但詳細診斷仍可使用：

```powershell
.\.venv\Scripts\python.exe -m yt_dlp --verbose --simulate "YOUTUBE_URL"
```

## 9. TLS 憑證繞過

一般情況下，HTTPS 憑證驗證保持啟用。只有明確提供以下旗標時：

```powershell
--no-check-certificates
```

`app.py` 才會顯示安全警告，並把 `no_check_certificates=True` 傳給下載服務；
`build_ydl_options()` 再設定 yt-dlp 的 `nocheckcertificate=True`。

```mermaid
flowchart TD
    Flag{"有 --no-check-certificates？"}
    Flag -->|否| Verify["正常驗證 TLS 憑證<br/>預設且建議"]
    Flag -->|是| Warn["CLI 顯示安全警告"]
    Warn --> Disable["yt-dlp nocheckcertificate=true"]
    Disable --> Risk["無法驗證遠端伺服器身分<br/>存在中間人攻擊風險"]
```

此功能只應作為受信任公司網路的暫時相容方案。正式環境應由 IT 提供公司 CA，
讓 Python 正常驗證憑證。

## 10. 測試策略

- `test_app.py` mock 下載服務，驗證參數、互動模式、TLS 警告及退出碼。
- `test_downloader.py` mock `YoutubeDL`，不連線到 YouTube 即可驗證格式選擇、
  metadata、進度、檔案跳過、直播拒絕及錯誤分類。
- 真實端對端測試使用有權下載的短影片，最後以 `ffprobe` 驗證格式、位元率及
  metadata。

```mermaid
flowchart LR
    Unit["Unit Tests"] --> AppTests["CLI Tests<br/>mock download_youtube"]
    Unit --> CoreTests["Downloader Tests<br/>mock YoutubeDL"]
    E2E["Authorized E2E Test"] --> Real["YouTube + yt-dlp + FFmpeg"]
    Real --> Probe["ffprobe 驗證<br/>codec / bitrate / metadata"]
```
