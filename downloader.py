"""以 yt-dlp 與 FFmpeg 實作單支 YouTube 內容下載。"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO
from urllib.parse import parse_qs, urlparse

try:
    import yt_dlp
except ImportError:  # 讓 CLI 能顯示易懂的安裝提示
    yt_dlp = None  # type: ignore[assignment]


YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
}
SINGLE_VIDEO_PATHS = {"shorts", "live", "embed", "v"}
OUTPUT_FORMATS = {"mp4", "mp3"}
VIDEO_QUALITIES = {"720", "1080", "best"}
OUTPUT_TEMPLATE = "%(title)s [%(id)s].%(ext)s"


class AppConfigurationError(RuntimeError):
    """缺少依賴或呼叫參數錯誤。"""


class DownloadFailure(RuntimeError):
    """下載或後製失敗。"""


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    title: str
    skipped: bool


def validate_youtube_url(url: str) -> str:
    """驗證網址是 YouTube 的單一影片內容，而不是播放清單。"""
    candidate = url.strip()
    if not candidate:
        raise AppConfigurationError("YouTube 連結不可為空")

    try:
        parsed = urlparse(candidate)
    except ValueError as exc:
        raise AppConfigurationError("YouTube 連結格式無效") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise AppConfigurationError("連結必須以 http:// 或 https:// 開頭")

    try:
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError as exc:
        raise AppConfigurationError("YouTube 連結格式無效") from exc

    path_parts = [part for part in parsed.path.split("/") if part]

    if host == "youtu.be":
        if not path_parts:
            raise AppConfigurationError("youtu.be 連結缺少影片 ID")
        return candidate

    if host not in YOUTUBE_HOSTS:
        raise AppConfigurationError("只支援 YouTube 網址")

    if parsed.path.rstrip("/") == "/playlist":
        raise AppConfigurationError("第一版不支援播放清單")

    if parsed.path.rstrip("/") == "/watch":
        video_ids = parse_qs(parsed.query).get("v", [])
        if not video_ids or not video_ids[0].strip():
            raise AppConfigurationError("YouTube watch 連結缺少影片 ID")
        return candidate

    if len(path_parts) >= 2 and path_parts[0].lower() in SINGLE_VIDEO_PATHS:
        return candidate

    raise AppConfigurationError("請提供單支 YouTube 影片、Shorts 或直播重播連結")


def check_environment(
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """確認必要元件，並回傳不影響啟動的警告。"""
    if yt_dlp is None:
        raise AppConfigurationError(
            "找不到 yt-dlp；請先執行 py -m pip install -r requirements.txt"
        )

    missing = [name for name in ("ffmpeg", "ffprobe") if which(name) is None]
    if missing:
        raise AppConfigurationError(
            f"找不到 {', '.join(missing)}；請安裝 FFmpeg 並加入 PATH"
        )

    warnings = []
    if which("node") is None and which("deno") is None:
        warnings.append(
            "找不到 Node.js 或 Deno；部分 YouTube 影片可能無法完整解析"
        )
    return warnings


def _video_format_selector(quality: str) -> str:
    if quality == "best":
        return "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"

    return (
        f"bv*[ext=mp4][height<={quality}]+ba[ext=m4a]"
        f"/b[ext=mp4][height<={quality}]"
        f"/bv*[height<={quality}]+ba"
        f"/b[height<={quality}]"
    )


def _format_bytes_per_second(speed: float | int | None) -> str:
    if not speed or speed <= 0:
        return "--"
    units = ("B/s", "KiB/s", "MiB/s", "GiB/s")
    value = float(speed)
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.1f} {units[index]}"


def _format_eta(seconds: float | int | None) -> str:
    if seconds is None or not math.isfinite(float(seconds)) or seconds < 0:
        return "--"
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class ProgressReporter:
    """將 yt-dlp hook 資料轉為穩定、簡潔的終端輸出。"""

    def __init__(self, stream: TextIO):
        self.stream = stream
        self.title = ""
        self.download_started = False
        self.rejected_reason: str | None = None
        self._announced = False
        self._line_open = False

    def announce(self, info: dict[str, Any]) -> None:
        if self._announced:
            return
        self.title = str(info.get("title") or info.get("id") or "未知標題")
        self.stream.write(f"標題：{self.title}\n")
        self.stream.flush()
        self._announced = True

    def filter(self, info: dict[str, Any], *, incomplete: bool = False) -> str | None:
        if incomplete:
            return None
        self.announce(info)
        live_status = info.get("live_status")
        if info.get("is_live") or live_status == "is_live":
            self.rejected_reason = "進行中的直播暫不支援；請等待直播結束後再下載"
            return self.rejected_reason
        return None

    def progress_hook(self, data: dict[str, Any]) -> None:
        status = data.get("status")
        info = data.get("info_dict") or {}
        if isinstance(info, dict):
            self.announce(info)

        if status == "downloading":
            self.download_started = True
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            percent = f"{(downloaded / total * 100):5.1f}%" if total else "  ---%"
            speed = _format_bytes_per_second(data.get("speed"))
            eta = _format_eta(data.get("eta"))
            self.stream.write(
                f"\r下載中：{percent} | {speed} | 剩餘 {eta}          "
            )
            self.stream.flush()
            self._line_open = True
        elif status == "finished":
            self.download_started = True
            if self._line_open:
                self.stream.write("\n")
            self.stream.write("媒體下載完成，正在進行合併或轉檔…\n")
            self.stream.flush()
            self._line_open = False
        elif status == "error":
            if self._line_open:
                self.stream.write("\n")
                self.stream.flush()
                self._line_open = False

    def postprocessor_hook(self, data: dict[str, Any]) -> None:
        if data.get("status") == "started":
            name = data.get("postprocessor") or "FFmpeg"
            self.stream.write(f"後製處理：{name}\n")
            self.stream.flush()


class YTDLPLogger:
    """保存 yt-dlp 錯誤內容，避免直接解析或依賴一般 stdout。"""

    def __init__(self) -> None:
        self.last_error = ""

    def debug(self, message: str) -> None:
        return None

    def warning(self, message: str) -> None:
        return None

    def error(self, message: str) -> None:
        self.last_error = message


def build_ydl_options(
    *,
    output_format: str,
    quality: str,
    output_dir: Path,
    reporter: ProgressReporter,
    logger: YTDLPLogger,
    no_check_certificates: bool = False,
    js_runtime: str | None = None,
) -> dict[str, Any]:
    """建立固定、可測試的 yt-dlp 設定。"""
    if output_format not in OUTPUT_FORMATS:
        raise AppConfigurationError("輸出格式只能是 mp4 或 mp3")
    if quality not in VIDEO_QUALITIES:
        raise AppConfigurationError("MP4 畫質只能是 720、1080 或 best")
    if output_format == "mp3" and quality != "1080":
        raise AppConfigurationError("MP3 不支援畫質選項")

    options: dict[str, Any] = {
        "outtmpl": str(output_dir / OUTPUT_TEMPLATE),
        "noplaylist": True,
        "overwrites": False,
        "continuedl": True,
        "nopart": False,
        "windowsfilenames": True,
        "trim_file_name": 180,
        "quiet": True,
        "no_warnings": True,
        "logger": logger,
        "progress_hooks": [reporter.progress_hook],
        "postprocessor_hooks": [reporter.postprocessor_hook],
        "match_filter": reporter.filter,
    }
    if no_check_certificates:
        options["nocheckcertificate"] = True
    if js_runtime:
        options["js_runtimes"] = {js_runtime: {}}

    if output_format == "mp4":
        options.update(
            {
                "format": _video_format_selector(quality),
                "merge_output_format": "mp4",
            }
        )
    else:
        options.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    },
                    {
                        "key": "FFmpegMetadata",
                        "add_metadata": True,
                    },
                ],
            }
        )

    return options


def _expected_output_path(ydl: Any, info: dict[str, Any], extension: str) -> Path:
    final_info = dict(info)
    final_info["ext"] = extension
    return Path(ydl.prepare_filename(final_info)).resolve()


def _friendly_download_error(message: str) -> str:
    normalized = message.lower()

    if "進行中的直播" in message or "is live" in normalized:
        return "進行中的直播暫不支援；請等待直播結束後再下載"
    if any(
        marker in normalized
        for marker in (
            "sign in",
            "login",
            "private video",
            "members-only",
            "authentication",
            "age-restricted",
        )
    ):
        return "內容需要登入、受到年齡限制，或不是公開影片"
    if any(
        marker in normalized
        for marker in ("not available in your country", "geo", "region")
    ):
        return "內容受到地區限制，無法在目前位置下載"
    if any(
        marker in normalized
        for marker in (
            "video unavailable",
            "not available",
            "removed",
            "copyright",
            "scheduled for",
        )
    ):
        return "影片不存在、尚未開始，或目前無法使用"
    if any(
        marker in normalized
        for marker in (
            "timed out",
            "unable to download",
            "http error",
            "network",
            "connection",
            "ssl",
        )
    ):
        return "網路連線失敗，請檢查連線後重試"
    if any(
        marker in normalized
        for marker in ("ffmpeg", "postprocessing", "conversion failed")
    ):
        return "FFmpeg 合併或轉檔失敗"
    return "無法下載此影片；請確認網址有效，並嘗試更新 yt-dlp"


def download_youtube(
    *,
    url: str,
    output_format: str,
    quality: str = "1080",
    output_dir: Path,
    progress_stream: TextIO,
    no_check_certificates: bool = False,
) -> DownloadResult:
    """下載單支 YouTube 內容，成功時回傳最後檔案路徑。"""
    validated_url = validate_youtube_url(url)
    if yt_dlp is None:
        raise AppConfigurationError(
            "找不到 yt-dlp；請先執行 py -m pip install -r requirements.txt"
        )

    destination = output_dir.expanduser().resolve()
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AppConfigurationError(f"無法建立輸出資料夾：{destination}") from exc

    reporter = ProgressReporter(progress_stream)
    logger = YTDLPLogger()
    options = build_ydl_options(
        output_format=output_format,
        quality=quality,
        output_dir=destination,
        reporter=reporter,
        logger=logger,
        no_check_certificates=no_check_certificates,
        js_runtime=(
            "deno"
            if shutil.which("deno")
            else "node"
            if shutil.which("node")
            else None
        ),
    )

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(validated_url, download=True)
            if reporter.rejected_reason:
                raise DownloadFailure(reporter.rejected_reason)
            if not isinstance(info, dict):
                raise DownloadFailure("yt-dlp 未回傳有效的影片資訊")
            if info.get("_type") == "playlist":
                raise AppConfigurationError("第一版不支援播放清單")

            final_path = _expected_output_path(ydl, info, output_format)
            if not final_path.exists():
                raise DownloadFailure(f"下載完成，但找不到輸出檔案：{final_path}")

            return DownloadResult(
                path=final_path,
                title=str(info.get("title") or info.get("id") or "未知標題"),
                skipped=not reporter.download_started,
            )
    except DownloadFailure:
        raise
    except KeyboardInterrupt:
        raise
    except yt_dlp.utils.DownloadError as exc:
        detail = logger.last_error or str(exc)
        raise DownloadFailure(_friendly_download_error(detail)) from exc
    except OSError as exc:
        raise DownloadFailure("無法寫入輸出檔案或啟動 FFmpeg") from exc
