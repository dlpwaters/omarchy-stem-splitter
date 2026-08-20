import json
import tempfile
import unittest
from pathlib import Path

import stem_tool


class StemToolTests(unittest.TestCase):
    def test_safe_track_name(self):
        self.assertEqual(stem_tool.safe_track_name(Path("  A  Great   Song.flac")), "A Great Song")
        self.assertEqual(stem_tool.safe_track_name(Path(".mp3")), "mp3")

    def test_unique_output_dir(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "Song").mkdir()
            (root / "Song-2").mkdir()
            self.assertEqual(stem_tool.unique_output_dir(root, "Song"), root / "Song-3")

    def test_parse_targets(self):
        self.assertEqual(stem_tool.parse_targets("vocals,drums,vocals"), ("vocals", "drums"))
        with self.assertRaises(stem_tool.StemSplitterError):
            stem_tool.parse_targets("")
        with self.assertRaises(stem_tool.StemSplitterError):
            stem_tool.parse_targets("vocals,drums,bass,other")
        with self.assertRaises(stem_tool.StemSplitterError):
            stem_tool.parse_targets("guitar")

    def test_classify_outputs(self):
        files = [
            Path("Song_(Vocals)_model.flac"),
            Path("Song_(Drums)_model.flac"),
            Path("Song_(Bass)_model.flac"),
            Path("Song_(Other)_model.flac"),
        ]
        result = stem_tool.classify_outputs(files)
        self.assertEqual(set(result), {"vocals", "drums", "bass", "other"})

    def test_validate_input(self):
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "track.flac"
            audio.write_bytes(b"not-empty")
            self.assertEqual(stem_tool.validate_input(str(audio)), audio.resolve())
            bad = Path(temp) / "track.txt"
            bad.write_text("audio")
            with self.assertRaises(stem_tool.StemSplitterError):
                stem_tool.validate_input(str(bad))

    def test_flac_publish_is_lossless_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.flac"
            destination = Path(temp) / "result.flac"
            source.write_bytes(b"lossless-audio-fixture")
            stem_tool.publish_audio(source, destination, "flac")
            self.assertEqual(destination.read_bytes(), source.read_bytes())

    def test_metadata_records_output_format(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)
            stem_tool.write_metadata(
                destination, Path("Song.wav"), "full", (), "model.yaml", "wav"
            )
            metadata = json.loads((destination / "separation.json").read_text())
            self.assertEqual(metadata["outputFormat"], "wav")


if __name__ == "__main__":
    unittest.main()
