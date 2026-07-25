"""YouTube MP4/MP3 下載器的命令列入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence, TextIO

from downloader import (
    AppConfigurationError,
    DownloadFailure,
    DownloadResult,
    check_environment,
    download_youtube,
)


class UsageError(ValueError):
    """命令列參數或互動輸入無效。"""


class ArgumentParser(argparse.ArgumentParser):
    """讓 argparse 的錯誤可由 main 統一轉換為退出碼 2。"""

    def error(self, message: str) -> None:
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = ArgumentParser(
        description="下載單支公開 YouTube 影片並輸出 MP4 或 MP3。",
    )
    parser.add_argument("url", nargs="?", help="YouTube 影片、Shorts 或已結束直播網址")
    parser.add_argument(
        "-f",
        "--format",
        dest="output_format",
        choices=("mp4", "mp3"),
        help="輸出格式",
    )
    parser.add_argument(
        "-q",
        "--quality",
        choices=("720", "1080", "best"),
        help="MP4 畫質上限；預設 1080",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "downloads",
        help="輸出資料夾；預設為專案下的 downloads",
    )
    parser.add_argument(
        "--no-check-certificates",
        action="store_true",
        help="略過 HTTPS 憑證驗證（不安全，僅限受信任的攔截網路）",
    )
    return parser


def _is_interactive(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, OSError):
        return False


def _prompt_url(stdin: TextIO, stdout: TextIO) -> str:
    stdout.write("請貼上 YouTube 連結：")
    stdout.flush()
    value = stdin.readline()
    if not value:
        raise UsageError("未輸入 YouTube 連結")
    return value.strip()


def _prompt_format(stdin: TextIO, stdout: TextIO) -> str:
    while True:
        stdout.write("輸出格式 [mp4/mp3]：")
        stdout.flush()
        value = stdin.readline()
        if not value:
            raise UsageError("未選擇輸出格式")
        selected = value.strip().lower()
        if selected in {"mp4", "mp3"}:
            return selected
        stdout.write("格式只能是 mp4 或 mp3。\n")


def resolve_inputs(
    args: argparse.Namespace,
    *,
    stdin: TextIO,
    stdout: TextIO,
) -> tuple[str, str, str]:
    missing = []
    if not args.url:
        missing.append("URL")
    if not args.output_format:
        missing.append("--format")

    if missing and not _is_interactive(stdin):
        raise UsageError(f"非互動環境必須提供：{', '.join(missing)}")

    url = args.url or _prompt_url(stdin, stdout)
    output_format = args.output_format or _prompt_format(stdin, stdout)

    if output_format == "mp3" and args.quality is not None:
        raise UsageError("--quality 僅適用於 MP4")

    quality = args.quality or "1080"
    return url, output_format, quality


def _print_result(result: DownloadResult, stdout: TextIO) -> None:
    if result.skipped:
        stdout.write(f"檔案已存在，已跳過：{result.path}\n")
    else:
        stdout.write(f"完成：{result.path}\n")


def run(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        url, output_format, quality = resolve_inputs(
            args,
            stdin=stdin,
            stdout=stdout,
        )

        for warning in check_environment():
            stderr.write(f"警告：{warning}\n")
        if args.no_check_certificates:
            stderr.write(
                "安全警告：HTTPS 憑證驗證已停用；"
                "請只在你信任的公司網路中使用此模式。\n"
            )

        result = download_youtube(
            url=url,
            output_format=output_format,
            quality=quality,
            output_dir=args.output_dir,
            progress_stream=stderr,
            no_check_certificates=args.no_check_certificates,
        )
        _print_result(result, stdout)
        return 0
    except UsageError as exc:
        stderr.write(f"參數錯誤：{exc}\n")
        stderr.write(parser.format_usage())
        return 2
    except AppConfigurationError as exc:
        stderr.write(f"環境錯誤：{exc}\n")
        return 2
    except DownloadFailure as exc:
        stderr.write(f"下載失敗：{exc}\n")
        return 1
    except KeyboardInterrupt:
        stderr.write("\n已取消下載；未完成的 .part 檔案已保留，可供下次續傳。\n")
        return 130


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
