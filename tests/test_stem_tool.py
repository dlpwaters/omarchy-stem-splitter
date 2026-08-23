import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
                destination, Path("Song.wav"), "full", (), "model.yaml", "wav", "fast"
            )
            metadata = json.loads((destination / "separation.json").read_text())
            self.assertEqual(metadata["outputFormat"], "wav")
            self.assertEqual(metadata["processingProfile"], "fast")

    def test_engine_progress_mapping(self):
        self.assertEqual(stem_tool.mapped_engine_progress(0, "loading"), 28)
        self.assertEqual(stem_tool.mapped_engine_progress(100, "loading"), 41)
        self.assertEqual(stem_tool.mapped_engine_progress(50, "separating"), 60)
        self.assertEqual(stem_tool.mapped_engine_progress(100, "separating"), 79)

    def test_job_state_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            state_home = Path(temp)
            state_path = state_home / "job.json"
            with (
                mock.patch.object(stem_tool, "STATE_HOME", state_home),
                mock.patch.object(stem_tool, "JOB_STATE_PATH", state_path),
            ):
                stem_tool.write_job_state({"jobId": "test", "status": "working", "percent": 42})
                state = stem_tool.load_job_state()
                self.assertIsNotNone(state)
                self.assertEqual(state["jobId"], "test")
                self.assertEqual(state["status"], "working")
                self.assertIn("updatedAt", state)

    def test_start_parser_defaults_to_best_profile(self):
        args = stem_tool.build_parser().parse_args([
            "start", "--mode", "remove", "/tmp/song.flac"
        ])
        self.assertEqual(args.profile, "best")

    def test_status_does_not_fail_job_when_service_state_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            state_home = Path(temp)
            state_path = state_home / "job.json"
            with (
                mock.patch.object(stem_tool, "STATE_HOME", state_home),
                mock.patch.object(stem_tool, "JOB_STATE_PATH", state_path),
                mock.patch.object(stem_tool, "unit_is_active", return_value=None),
                mock.patch("sys.stdout", new=io.StringIO()),
            ):
                stem_tool.write_job_state({"jobId": "test", "status": "working", "percent": 42})
                stem_tool.job_status()
                self.assertEqual(stem_tool.load_job_state()["status"], "working")

    def test_dependency_lock_covers_the_complete_engine(self):
        locked = stem_tool.locked_requirements()
        for name, version in {
            "audio-separator": stem_tool.ENGINE_VERSION,
            "torch": stem_tool.PYTORCH_VERSION,
            "torchvision": stem_tool.TORCHVISION_VERSION,
            "audioread": stem_tool.AUDIOREAD_VERSION,
            "librosa": stem_tool.LIBROSA_VERSION,
        }.items():
            self.assertEqual(locked[name], version)
        lock_text = stem_tool.REQUIREMENTS_LOCK.read_text(encoding="utf-8")
        self.assertIn("--hash=sha256:", lock_text)

    def test_source_build_toolchain_is_pinned_and_hashed(self):
        lock_text = stem_tool.BUILD_REQUIREMENTS_LOCK.read_text(encoding="utf-8")
        for dependency in ("cython", "setuptools", "wheel"):
            self.assertTrue(any(
                line.startswith(f"{dependency}==") and line.endswith(" \\")
                for line in lock_text.splitlines()
            ))
        self.assertIn("--hash=sha256:", lock_text)

    def test_model_lock_covers_every_selectable_model_and_hash(self):
        lock = stem_tool.model_lock()
        files = lock["files"]
        models = lock["models"]
        for model in (
            stem_tool.VOCAL_MODEL,
            stem_tool.FOUR_STEM_MODEL,
            stem_tool.FAST_VOCAL_MODEL,
            stem_tool.FAST_FOUR_STEM_MODEL,
        ):
            self.assertIn(model, models)
            for filename in models[model]:
                self.assertIn(filename, files)
                self.assertRegex(files[filename]["sha256"], r"^[0-9a-f]{64}$")
                self.assertGreater(files[filename]["bytes"], 0)
                self.assertTrue(files[filename]["url"].startswith("https://"))

    def test_locked_model_file_match_rejects_wrong_size_and_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "model.bin"
            path.write_bytes(b"reviewed")
            record = {
                "bytes": len(b"reviewed"),
                "sha256": "e4f934f321eb76c9bf8b5103e0a0d9afe72d6e62ace3d3ea849790619bf7487a",
            }
            self.assertTrue(stem_tool.locked_model_file_matches(path, record))
            record["bytes"] += 1
            self.assertFalse(stem_tool.locked_model_file_matches(path, record))


if __name__ == "__main__":
    unittest.main()
