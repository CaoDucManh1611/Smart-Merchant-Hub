import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.zalo_media import normalize_zalo_audio_upload


class ZaloMediaTests(unittest.TestCase):
    def test_existing_aac_upload_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "voice.aac"
            source.write_bytes(b"aac")

            with patch("app.services.zalo_media.shutil.which") as which, patch(
                "app.services.zalo_media.subprocess.run"
            ) as run:
                path, content_type = normalize_zalo_audio_upload(
                    source,
                    content_type="audio/aac",
                )

        self.assertEqual(source, path)
        self.assertEqual("audio/aac", content_type)
        which.assert_not_called()
        run.assert_not_called()

    def test_browser_audio_is_transcoded_to_adts_aac(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "voice.webm"
            source.write_bytes(b"webm")

            def transcode(command, **kwargs):
                Path(command[-1]).write_bytes(b"aac")
                return type("Completed", (), {"returncode": 0})()

            with patch("app.services.zalo_media.shutil.which", return_value="ffmpeg"), patch(
                "app.services.zalo_media.subprocess.run", side_effect=transcode
            ) as run:
                path, content_type = normalize_zalo_audio_upload(
                    source,
                    content_type="audio/webm",
                )

        self.assertEqual("voice.aac", path.name)
        self.assertEqual("audio/aac", content_type)
        command = run.call_args.args[0]
        self.assertIn("-f", command)
        self.assertIn("adts", command)
        self.assertEqual("ffmpeg", command[0])

    def test_transcode_failure_does_not_leave_partial_aac(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "voice.ogg"
            source.write_bytes(b"ogg")

            def failed_transcode(command, **kwargs):
                Path(command[-1]).write_bytes(b"partial")
                return type("Completed", (), {"returncode": 1})()

            with patch("app.services.zalo_media.shutil.which", return_value="ffmpeg"), patch(
                "app.services.zalo_media.subprocess.run", side_effect=failed_transcode
            ):
                with self.assertRaisesRegex(RuntimeError, "AAC"):
                    normalize_zalo_audio_upload(source, content_type="audio/ogg")

            self.assertFalse((Path(directory) / "voice.aac").exists())


if __name__ == "__main__":
    unittest.main()
