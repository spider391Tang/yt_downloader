from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import downloader


class FakeDownloadError(Exception):
    pass


class FakeYoutubeDL:
    last_options = None
    error_message: str | None = None
    live = False

    def __init__(self, options):
        self.options = options
        type(self).last_options = options

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def prepare_filename(self, info):
        output = self.options["outtmpl"]
        filename = output.replace("%(title)s", info["title"])
        filename = filename.replace("%(id)s", info["id"])
        filename = filename.replace("%(ext)s", info["ext"])
        return filename

    def extract_info(self, url, download):
        if type(self).error_message:
            message = type(self).error_message
            self.options["logger"].error(message)
            raise FakeDownloadError(message)

        info = {
            "title": "測試影片",
            "id": "abcdefghijk",
            "ext": "webm",
            "is_live": type(self).live,
            "live_status": "is_live" if type(self).live else "was_live",
        }
        rejected = self.options["match_filter"](info, incomplete=False)
        if rejected:
            return info

        extension = (
            "mp3" if self.options.get("postprocessors") else "mp4"
        )
        final_info = {**info, "ext": extension}
        final_path = Path(self.prepare_filename(final_info))

        if not final_path.exists():
            self.options["progress_hooks"][0](
                {
                    "status": "downloading",
                    "downloaded_bytes": 50,
                    "total_bytes": 100,
                    "speed": 1024,
                    "eta": 1,
                    "info_dict": info,
                }
            )
            final_path.parent.mkdir(parents=True, exist_ok=True)
            final_path.write_bytes(b"fake media")
            self.options["progress_hooks"][0](
                {"status": "finished", "info_dict": info}
            )
        return info


def fake_yt_dlp():
    return SimpleNamespace(
        YoutubeDL=FakeYoutubeDL,
        utils=SimpleNamespace(DownloadError=FakeDownloadError),
    )


class ValidateUrlTests(unittest.TestCase):
    def test_accepts_watch_url_with_playlist_query_as_single_video(self):
        url = "https://www.youtube.com/watch?v=abcdefghijk&list=PL123"
        self.assertEqual(downloader.validate_youtube_url(url), url)

    def test_accepts_short_and_share_urls(self):
        for url in (
            "https://youtube.com/shorts/abcdefghijk",
            "https://youtu.be/abcdefghijk?t=10",
            "https://m.youtube.com/live/abcdefghijk",
        ):
            with self.subTest(url=url):
                self.assertEqual(downloader.validate_youtube_url(url), url)

    def test_rejects_playlist_only_url(self):
        with self.assertRaisesRegex(
            downloader.AppConfigurationError, "不支援播放清單"
        ):
            downloader.validate_youtube_url(
                "https://www.youtube.com/playlist?list=PL123"
            )

    def test_rejects_non_youtube_and_domain_suffix_tricks(self):
        for url in (
            "https://example.com/watch?v=abcdefghijk",
            "https://youtube.com.example.org/watch?v=abcdefghijk",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(
                    downloader.AppConfigurationError, "只支援 YouTube"
                ):
                    downloader.validate_youtube_url(url)

    def test_rejects_url_without_http_scheme(self):
        with self.assertRaisesRegex(
            downloader.AppConfigurationError, "http://"
        ):
            downloader.validate_youtube_url("youtube.com/watch?v=abcdefghijk")


class EnvironmentTests(unittest.TestCase):
    def test_requires_ffmpeg_and_ffprobe(self):
        with mock.patch.object(downloader, "yt_dlp", object()):
            with self.assertRaisesRegex(
                downloader.AppConfigurationError, "ffprobe"
            ):
                downloader.check_environment(
                    which=lambda name: "tool.exe" if name == "ffmpeg" else None
                )

    def test_warns_when_javascript_runtime_is_missing(self):
        available = {"ffmpeg": "ffmpeg.exe", "ffprobe": "ffprobe.exe"}
        with mock.patch.object(downloader, "yt_dlp", object()):
            warnings = downloader.check_environment(which=available.get)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Node.js", warnings[0])


class OptionsTests(unittest.TestCase):
    def setUp(self):
        self.reporter = downloader.ProgressReporter(io.StringIO())
        self.logger = downloader.YTDLPLogger()

    def test_mp4_options_cap_resolution_and_forbid_playlist(self):
        options = downloader.build_ydl_options(
            output_format="mp4",
            quality="1080",
            output_dir=Path("downloads"),
            reporter=self.reporter,
            logger=self.logger,
        )
        self.assertTrue(options["noplaylist"])
        self.assertFalse(options["overwrites"])
        self.assertTrue(options["continuedl"])
        self.assertIn("height<=1080", options["format"])
        self.assertEqual(options["merge_output_format"], "mp4")

    def test_best_mp4_has_no_resolution_cap(self):
        options = downloader.build_ydl_options(
            output_format="mp4",
            quality="best",
            output_dir=Path("downloads"),
            reporter=self.reporter,
            logger=self.logger,
        )
        self.assertNotIn("height<=", options["format"])

    def test_mp3_options_extract_192k_and_add_metadata(self):
        options = downloader.build_ydl_options(
            output_format="mp3",
            quality="1080",
            output_dir=Path("downloads"),
            reporter=self.reporter,
            logger=self.logger,
        )
        processors = options["postprocessors"]
        self.assertEqual(processors[0]["key"], "FFmpegExtractAudio")
        self.assertEqual(processors[0]["preferredquality"], "192")
        self.assertEqual(processors[1]["key"], "FFmpegMetadata")
        self.assertNotIn("writethumbnail", options)

    def test_rejects_mp3_quality_override(self):
        with self.assertRaisesRegex(
            downloader.AppConfigurationError, "MP3 不支援"
        ):
            downloader.build_ydl_options(
                output_format="mp3",
                quality="720",
                output_dir=Path("downloads"),
                reporter=self.reporter,
                logger=self.logger,
            )

    def test_can_explicitly_disable_certificate_checks_and_enable_node(self):
        options = downloader.build_ydl_options(
            output_format="mp3",
            quality="1080",
            output_dir=Path("downloads"),
            reporter=self.reporter,
            logger=self.logger,
            no_check_certificates=True,
            js_runtime="node",
        )
        self.assertTrue(options["nocheckcertificate"])
        self.assertEqual(options["js_runtimes"], {"node": {}})


class DownloadTests(unittest.TestCase):
    def setUp(self):
        FakeYoutubeDL.error_message = None
        FakeYoutubeDL.live = False
        self.yt_dlp_patch = mock.patch.object(
            downloader, "yt_dlp", fake_yt_dlp()
        )
        self.yt_dlp_patch.start()

    def tearDown(self):
        self.yt_dlp_patch.stop()

    def test_download_returns_mp3_final_path_and_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            progress = io.StringIO()
            result = downloader.download_youtube(
                url="https://youtu.be/abcdefghijk",
                output_format="mp3",
                output_dir=Path(temp_dir),
                progress_stream=progress,
            )

            self.assertTrue(result.path.exists())
            self.assertEqual(result.path.suffix, ".mp3")
            self.assertFalse(result.skipped)
            self.assertIn("50.0%", progress.getvalue())
            self.assertIn("正在進行合併或轉檔", progress.getvalue())

    def test_existing_file_is_skipped_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            existing = Path(temp_dir) / "測試影片 [abcdefghijk].mp4"
            existing.write_bytes(b"original")

            result = downloader.download_youtube(
                url="https://youtu.be/abcdefghijk",
                output_format="mp4",
                output_dir=Path(temp_dir),
                progress_stream=io.StringIO(),
            )

            self.assertTrue(result.skipped)
            self.assertEqual(existing.read_bytes(), b"original")

    def test_rejects_active_live_stream(self):
        FakeYoutubeDL.live = True
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                downloader.DownloadFailure, "進行中的直播"
            ):
                downloader.download_youtube(
                    url="https://youtube.com/live/abcdefghijk",
                    output_format="mp4",
                    output_dir=Path(temp_dir),
                    progress_stream=io.StringIO(),
                )

    def test_maps_private_video_error(self):
        FakeYoutubeDL.error_message = "Private video. Sign in to continue"
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                downloader.DownloadFailure, "需要登入"
            ):
                downloader.download_youtube(
                    url="https://youtu.be/abcdefghijk",
                    output_format="mp4",
                    output_dir=Path(temp_dir),
                    progress_stream=io.StringIO(),
                )

    def test_keyboard_interrupt_is_not_swallowed(self):
        class InterruptingYDL(FakeYoutubeDL):
            def extract_info(self, url, download):
                raise KeyboardInterrupt

        module = SimpleNamespace(
            YoutubeDL=InterruptingYDL,
            utils=SimpleNamespace(DownloadError=FakeDownloadError),
        )
        with mock.patch.object(downloader, "yt_dlp", module):
            with tempfile.TemporaryDirectory() as temp_dir:
                with self.assertRaises(KeyboardInterrupt):
                    downloader.download_youtube(
                        url="https://youtu.be/abcdefghijk",
                        output_format="mp4",
                        output_dir=Path(temp_dir),
                        progress_stream=io.StringIO(),
                    )


if __name__ == "__main__":
    unittest.main()
