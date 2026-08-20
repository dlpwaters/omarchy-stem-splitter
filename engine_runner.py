#!/usr/bin/env python3
"""Run one pinned Audio Separator model and report structured output paths."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path


def emit(percent: int, message: str) -> None:
    print(f"EVENT\t{percent}\t{message}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--single-stem")
    args = parser.parse_args()

    from audio_separator.separator import Separator

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    emit(18, "Loading the separation engine…")
    separator = Separator(
        log_level=logging.INFO,
        model_file_dir=args.model_dir,
        output_dir=str(output_dir),
        output_format="FLAC",
        output_single_stem=args.single_stem,
        sample_rate=44100,
        use_soundfile=False,
        demucs_params={"segment_size": "Default", "shifts": 2, "overlap": 0.25, "segments_enabled": True},
        mdxc_params={"segment_size": 256, "override_model_segment_size": False, "batch_size": 1, "overlap": 8, "pitch_shift": 0},
    )
    emit(28, "Loading the model; first use downloads it once…")
    separator.load_model(model_filename=args.model)
    emit(42, "Separating the track locally…")
    outputs = separator.separate(args.input)
    emit(80, "Separation complete; preparing the result…")
    print("RESULT\t" + json.dumps(outputs), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
