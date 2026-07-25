from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest import mock

import app
from downloader import DownloadFailure, DownloadResult


class TTYStringIO(io.StringIO):
    def isatty(self):
        return True


class AppTests(unittest.TestCase):
    def test_noninteractive_missing_arguments_returns_2(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = app.run([], stdin=io.StringIO(), stdout=stdout, stderr=stderr)

        self.assertEqual(code, 2)
        self.assertIn("非互動環境", stderr.getvalue())

    def test_interactive_mode_prompts_for_url_and_format(self):
        stdin = TTYStringIO("https://youtu.be/abcdefghijk\nmp3\n")
        stdout = io.StringIO()
        stderr = io.StringIO()
        result = DownloadResult(
            path=Path("song.mp3").resolve(),
            title="song",
            skipped=False,
        )

        with mock.patch.object(app, "check_environment", return_value=[]):
            with mock.patch.object(
                app, "download_youtube", return_value=result
            ) as download:
                code = app.run(
                    [], stdin=stdin, stdout=stdout, stderr=stderr
                )

        self.assertEqual(code, 0)
        self.assertIn("請貼上", stdout.getvalue())
        self.assertIn("完成", stdout.getvalue())
        self.assertEqual(download.call_args.kwargs["output_format"], "mp3")

    def test_mp3_rejects_quality_argument(self):
        stderr = io.StringIO()
        code = app.run(
            [
                "https://youtu.be/abcdefghijk",
                "--format",
                "mp3",
                "--quality",
                "720",
            ],
            stdin=io.StringIO(),
            stdout=io.StringIO(),
            stderr=stderr,
        )
        self.assertEqual(code, 2)
        self.assertIn("僅適用於 MP4", stderr.getvalue())

    def test_download_failure_returns_1(self):
        with mock.patch.object(app, "check_environment", return_value=[]):
            with mock.patch.object(
                app,
                "download_youtube",
                side_effect=DownloadFailure("網路連線失敗"),
            ):
                stderr = io.StringIO()
                code = app.run(
                    [
                        "https://youtu.be/abcdefghijk",
                        "--format",
                        "mp4",
                    ],
                    stdin=io.StringIO(),
                    stdout=io.StringIO(),
                    stderr=stderr,
                )

        self.assertEqual(code, 1)
        self.assertIn("網路連線失敗", stderr.getvalue())

    def test_no_check_certificates_is_forwarded_with_warning(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        result = DownloadResult(
            path=Path("song.mp3").resolve(),
            title="song",
            skipped=False,
        )
        with mock.patch.object(app, "check_environment", return_value=[]):
            with mock.patch.object(
                app, "download_youtube", return_value=result
            ) as download:
                code = app.run(
                    [
                        "https://youtu.be/abcdefghijk",
                        "--format",
                        "mp3",
                        "--no-check-certificates",
                    ],
                    stdin=io.StringIO(),
                    stdout=stdout,
                    stderr=stderr,
                )

        self.assertEqual(code, 0)
        self.assertTrue(
            download.call_args.kwargs["no_check_certificates"]
        )
        self.assertIn("憑證驗證已停用", stderr.getvalue())

    def test_keyboard_interrupt_returns_130(self):
        with mock.patch.object(app, "check_environment", return_value=[]):
            with mock.patch.object(
                app, "download_youtube", side_effect=KeyboardInterrupt
            ):
                stderr = io.StringIO()
                code = app.run(
                    [
                        "https://youtu.be/abcdefghijk",
                        "--format",
                        "mp4",
                    ],
                    stdin=io.StringIO(),
                    stdout=io.StringIO(),
                    stderr=stderr,
                )

        self.assertEqual(code, 130)
        self.assertIn(".part", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
