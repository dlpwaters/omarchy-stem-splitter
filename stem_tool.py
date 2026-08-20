#!/usr/bin/env python3
"""Local orchestration for the Omarchy Stem Splitter plugin."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PLUGIN_VERSION = "1.0.1"
ENGINE_VERSION = "0.44.5"
PYTHON_VERSION = "3.12"
PYTORCH_VERSION = "2.13.0+cpu"
TORCHVISION_VERSION = "0.28.0+cpu"
AUDIOREAD_VERSION = "3.1.0"
LIBROSA_VERSION = "0.10.2.post1"
PYTORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
VOCAL_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
FOUR_STEM_MODEL = "htdemucs_ft.yaml"
FAST_VOCAL_MODEL = "UVR-MDX-NET-Inst_HQ_3.onnx"
FAST_FOUR_STEM_MODEL = "htdemucs.yaml"
STEMS = ("vocals", "drums", "bass", "other")
OUTPUT_FORMATS = ("flac", "wav", "mp4")
PROCESSING_PROFILES = ("best", "fast")
SUPPORTED_SUFFIXES = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".oga", ".aac", ".wma", ".aiff", ".aif"}

HOME = Path.home()
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "omarchy-stem-splitter"
CACHE_HOME = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "omarchy-stem-splitter"
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state")) / "omarchy-stem-splitter"
VENV_DIR = DATA_HOME / "venv"
ENGINE_PYTHON = VENV_DIR / "bin/python"
MODEL_DIR = DATA_HOME / "models"
OUTPUT_ROOT = HOME / "Desktop/stems"
LOCK_PATH = STATE_HOME / "operation.lock"
ERROR_LOG = STATE_HOME / "last-error.log"
JOB_STATE_PATH = STATE_HOME / "job.json"
JOB_UNIT = "omarchy-stem-splitter-job.service"

ACTIVE_JOB_ID: str | None = None
STATE_LOCK = threading.Lock()


class StemSplitterError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_job_state() -> dict[str, object] | None:
    try:
        value = json.loads(JOB_STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def write_job_state(state: dict[str, object]) -> None:
    STATE_HOME.mkdir(parents=True, exist_ok=True)
    state["updatedAt"] = utc_now()
    with STATE_LOCK:
        descriptor, temporary_name = tempfile.mkstemp(prefix="job-", suffix=".tmp", dir=STATE_HOME)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(state, indent=2) + "\n")
            os.replace(temporary, JOB_STATE_PATH)
        finally:
            temporary.unlink(missing_ok=True)


def update_job_state(**changes: object) -> None:
    if ACTIVE_JOB_ID is None:
        return
    state = load_job_state() or {}
    if state.get("jobId") != ACTIVE_JOB_ID:
        return
    state.update(changes)
    write_job_state(state)


def emit(kind: str, *values: object) -> None:
    fields = [kind, *(str(value).replace("\t", " ").replace("\n", " ") for value in values)]
    if kind == "EVENT" and len(values) >= 2:
        try:
            percent = max(0, min(100, int(values[0])))
        except (TypeError, ValueError):
            percent = 0
        update_job_state(status="working", percent=percent, message=str(values[1]))
    elif kind == "DONE" and values:
        update_job_state(
            status="finished",
            percent=100,
            message="Finished. Your files are on the Desktop.",
            outputPath=str(values[0]),
            finishedAt=utc_now(),
        )
    print("\t".join(fields), flush=True)


def require_command(command: str) -> str:
    found = shutil.which(command)
    if not found:
        raise StemSplitterError(f"Required command not found: {command}")
    return found


def safe_track_name(path: Path) -> str:
    name = path.stem.strip().lstrip(".") or "track"
    name = re.sub(r"[\x00-\x1f\x7f/\\]+", "-", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120] or "track"


def unique_output_dir(root: Path, track_name: str) -> Path:
    candidate = root / track_name
    counter = 2
    while candidate.exists():
        candidate = root / f"{track_name}-{counter}"
        counter += 1
    return candidate


def classify_outputs(files: Iterable[Path]) -> dict[str, Path]:
    classified: dict[str, Path] = {}
    for file_path in files:
        lowered = file_path.name.lower()
        for stem in (*STEMS, "instrumental"):
            patterns = (f"({stem})", f"_{stem}_", f"-{stem}-", f" {stem} ")
            if any(pattern in lowered for pattern in patterns):
                classified[stem] = file_path
                break
    return classified


def parse_targets(value: str) -> tuple[str, ...]:
    targets = tuple(dict.fromkeys(item.strip().lower() for item in value.split(",") if item.strip()))
    unknown = sorted(set(targets) - set(STEMS))
    if unknown:
        raise StemSplitterError(f"Unknown removal target: {', '.join(unknown)}")
    if not targets:
        raise StemSplitterError("Select at least one part to remove.")
    if len(targets) == len(STEMS):
        raise StemSplitterError("Keep at least one part in the cleaned mix.")
    return targets


def validate_input(path_text: str) -> Path:
    source = Path(path_text).expanduser().resolve()
    if not source.is_file():
        raise StemSplitterError("The selected audio file no longer exists.")
    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise StemSplitterError(f"Unsupported audio format: {source.suffix or 'unknown'}")
    if source.stat().st_size == 0:
        raise StemSplitterError("The selected audio file is empty.")
    return source


def engine_ready() -> tuple[bool, str]:
    if not ENGINE_PYTHON.is_file():
        return False, "Audio engine setup is required."
    check = subprocess.run(
        [
            str(ENGINE_PYTHON),
            "-c",
            "import importlib.metadata as m; from audio_separator.separator import Separator; "
            "print('|'.join(m.version(name) for name in "
            "('audio-separator', 'torch', 'torchvision', 'audioread', 'librosa')))",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    version_set = check.stdout.strip()
    expected = "|".join(
        (ENGINE_VERSION, PYTORCH_VERSION, TORCHVISION_VERSION, AUDIOREAD_VERSION, LIBROSA_VERSION)
    )
    if check.returncode != 0 or version_set != expected:
        return False, f"Audio engine {ENGINE_VERSION} setup is required."
    return True, f"Audio Separator {ENGINE_VERSION} is ready."


def operation_lock():
    STATE_HOME.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise StemSplitterError("Another setup or separation job is already running.") from exc
    return handle


def run_checked(command: list[str], env: dict[str, str] | None = None) -> None:
    process = subprocess.run(command, text=True, capture_output=True, env=env, check=False)
    if process.returncode != 0:
        details = (process.stderr or process.stdout).strip()
        raise StemSplitterError(details.splitlines()[-1] if details else f"Command failed: {command[0]}")


def setup_engine() -> int:
    with operation_lock():
        uv = require_command("uv")
        require_command("ffmpeg")
        DATA_HOME.mkdir(parents=True, exist_ok=True)
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        emit("EVENT", 8, f"Preparing Python {PYTHON_VERSION}…")
        if not ENGINE_PYTHON.is_file():
            run_checked([uv, "venv", "--python", PYTHON_VERSION, "--python-preference", "managed", str(VENV_DIR)])
        emit("EVENT", 24, "Installing the CPU audio runtime…")
        run_checked([
            uv, "pip", "install", "--python", str(ENGINE_PYTHON),
            "--default-index", PYTORCH_CPU_INDEX,
            f"torch=={PYTORCH_VERSION}",
            f"torchvision=={TORCHVISION_VERSION}",
        ])
        emit("EVENT", 42, f"Installing Audio Separator {ENGINE_VERSION}…")
        run_checked([
            uv, "pip", "install", "--python", str(ENGINE_PYTHON),
            f"audio-separator[cpu]=={ENGINE_VERSION}",
            f"audioread=={AUDIOREAD_VERSION}",
            f"librosa=={LIBROSA_VERSION}",
        ])
        ready, message = engine_ready()
        if not ready:
            raise StemSplitterError(message)
        emit("EVENT", 96, "Checking FFmpeg and the isolated environment…")
        emit("READY", message)
        return 0


def mapped_engine_progress(raw_percent: int, phase: str) -> int:
    raw_percent = max(0, min(100, raw_percent))
    if phase == "separating":
        return min(79, 42 + round(raw_percent * 0.37))
    return min(41, 28 + round(raw_percent * 0.13))


def call_engine(
    source: Path,
    model: str,
    output_dir: Path,
    single_stem: str | None,
    profile: str,
) -> list[Path]:
    runner = Path(__file__).with_name("engine_runner.py")
    command = [
        str(ENGINE_PYTHON), str(runner), "--input", str(source), "--model", model,
        "--output-dir", str(output_dir), "--model-dir", str(MODEL_DIR),
        "--profile", profile,
    ]
    if single_stem:
        command.extend(["--single-stem", single_stem])

    ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ERROR_LOG.open("w", encoding="utf-8") as error_log:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        phase = {"name": "loading"}
        progress_lock = threading.Lock()
        last_progress = {"value": 0}

        def report_engine_progress(raw_percent: int) -> None:
            overall = mapped_engine_progress(raw_percent, phase["name"])
            with progress_lock:
                if overall <= last_progress["value"]:
                    return
                last_progress["value"] = overall
            message = "Separating the track locally…" if phase["name"] == "separating" else "Loading the model…"
            emit("EVENT", overall, message)

        def drain_stderr() -> None:
            assert process.stderr is not None
            line: list[str] = []
            while True:
                character = process.stderr.read(1)
                if character == "":
                    break
                error_log.write(character)
                if character in "\r\n":
                    error_log.flush()
                    match = re.search(r"(\d{1,3})%\|", "".join(line))
                    if match:
                        report_engine_progress(int(match.group(1)))
                    line.clear()
                else:
                    line.append(character)
            if line:
                error_log.write("\n")
                error_log.flush()

        stderr_thread = threading.Thread(target=drain_stderr, name="separator-log", daemon=True)
        stderr_thread.start()

        def terminate_child(_signum, _frame):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            raise KeyboardInterrupt

        previous_term = signal.signal(signal.SIGTERM, terminate_child)
        result_files: list[Path] = []
        try:
            assert process.stdout is not None
            for line in process.stdout:
                line = line.rstrip("\n")
                if line.startswith("RESULT\t"):
                    payload = json.loads(line.split("\t", 1)[1])
                    result_files = [Path(item) if Path(item).is_absolute() else output_dir / item for item in payload]
                elif line.startswith("EVENT\t"):
                    parts = line.split("\t", 2)
                    percent = int(parts[1])
                    if percent >= 42:
                        phase["name"] = "separating"
                    emit("EVENT", percent, parts[2] if len(parts) > 2 else "Working…")
                else:
                    print(line, flush=True)
            return_code = process.wait()
            stderr_thread.join(timeout=5)
        finally:
            signal.signal(signal.SIGTERM, previous_term)

    if return_code != 0:
        details = ERROR_LOG.read_text(encoding="utf-8", errors="replace").strip()
        last_line = details.splitlines()[-1] if details else "Audio separation failed."
        raise StemSplitterError(last_line)
    if not result_files:
        raise StemSplitterError("The audio engine returned no output files.")
    missing = [path for path in result_files if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise StemSplitterError("The audio engine produced an incomplete output.")
    return result_files


def mix_remaining(stem_files: dict[str, Path], retained: tuple[str, ...], destination: Path) -> None:
    if len(retained) == 1:
        shutil.copy2(stem_files[retained[0]], destination)
        return
    ffmpeg = require_command("ffmpeg")
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for stem in retained:
        command.extend(["-i", str(stem_files[stem])])
    command.extend([
        "-filter_complex", f"amix=inputs={len(retained)}:duration=longest:dropout_transition=0:normalize=0",
        "-c:a", "flac", str(destination),
    ])
    run_checked(command)


def publish_audio(source: Path, destination: Path, output_format: str) -> None:
    if output_format == "flac":
        shutil.copy2(source, destination)
        return
    ffmpeg = require_command("ffmpeg")
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-vn"]
    if output_format == "wav":
        command.extend(["-c:a", "pcm_s16le", "-ar", "44100", str(destination)])
    elif output_format == "mp4":
        command.extend([
            "-c:a", "aac", "-b:a", "256k", "-ar", "44100",
            "-movflags", "+faststart", str(destination),
        ])
    else:
        raise StemSplitterError(f"Unsupported output format: {output_format}")
    run_checked(command)


def write_metadata(
    destination: Path,
    source: Path,
    mode: str,
    targets: tuple[str, ...],
    model: str,
    output_format: str,
    profile: str,
) -> None:
    metadata = {
        "plugin": "Omarchy Stem Splitter",
        "pluginVersion": PLUGIN_VERSION,
        "engine": "audio-separator",
        "engineVersion": ENGINE_VERSION,
        "model": model,
        "mode": mode,
        "removed": list(targets),
        "outputFormat": output_format,
        "processingProfile": profile,
        "sourceFile": source.name,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    (destination / "separation.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def process_track(
    source_text: str,
    mode: str,
    targets_text: str,
    output_format: str,
    profile: str,
) -> int:
    ready, message = engine_ready()
    if not ready:
        raise StemSplitterError(message)
    require_command("ffmpeg")
    source = validate_input(source_text)
    targets = parse_targets(targets_text) if mode == "remove" else ()
    if output_format not in OUTPUT_FORMATS:
        raise StemSplitterError(f"Unsupported output format: {output_format}")
    if profile not in PROCESSING_PROFILES:
        raise StemSplitterError(f"Unsupported processing profile: {profile}")

    with operation_lock():
        CACHE_HOME.mkdir(parents=True, exist_ok=True)
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix="job-", dir=CACHE_HOME))
        published = unique_output_dir(OUTPUT_ROOT, safe_track_name(source))
        staging = temporary / "published"
        staging.mkdir()
        model = FAST_FOUR_STEM_MODEL if profile == "fast" else FOUR_STEM_MODEL
        try:
            if mode == "remove" and targets == ("vocals",):
                model = FAST_VOCAL_MODEL if profile == "fast" else VOCAL_MODEL
                quality = "fast" if profile == "fast" else "high-quality"
                emit("EVENT", 10, f"Preparing the {quality} vocal-removal model…")
                outputs = call_engine(source, model, temporary / "engine", "Instrumental", profile)
                classified = classify_outputs(outputs)
                instrumental = classified.get("instrumental")
                if instrumental is None:
                    raise StemSplitterError("Could not identify the instrumental output.")
                emit("EVENT", 88, "Publishing the cleaned mix…")
                publish_audio(
                    instrumental,
                    staging / f"mix-without-vocals.{output_format}",
                    output_format,
                )
            else:
                quality = "fast" if profile == "fast" else "fine-tuned"
                emit("EVENT", 10, f"Preparing the {quality} four-stem model…")
                outputs = call_engine(source, model, temporary / "engine", None, profile)
                classified = classify_outputs(outputs)
                missing = [stem for stem in STEMS if stem not in classified]
                if missing:
                    raise StemSplitterError(f"Missing expected stem output: {', '.join(missing)}")
                if mode == "full":
                    emit("EVENT", 88, f"Publishing four {output_format.upper()} stems…")
                    for stem in STEMS:
                        publish_audio(
                            classified[stem],
                            staging / f"{stem}.{output_format}",
                            output_format,
                        )
                else:
                    retained = tuple(stem for stem in STEMS if stem not in targets)
                    emit("EVENT", 84, "Mixing the remaining parts…")
                    mixed = temporary / "retained-mix.flac"
                    mix_remaining(classified, retained, mixed)
                    publish_audio(
                        mixed,
                        staging / f"mix-without-{'-'.join(targets)}.{output_format}",
                        output_format,
                    )
            write_metadata(staging, source, mode, targets, model, output_format, profile)
            emit("EVENT", 96, "Verifying the finished files…")
            audio_outputs = list(staging.glob(f"*.{output_format}"))
            if not audio_outputs:
                raise StemSplitterError("No finished audio files were produced.")
            for output in audio_outputs:
                if output.stat().st_size == 0:
                    raise StemSplitterError(f"Empty output file: {output.name}")
            staging.rename(published)
            emit("DONE", published)
            return 0
        finally:
            shutil.rmtree(temporary, ignore_errors=True)


def unit_is_active() -> bool | None:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return None
    result = subprocess.run(
        [systemctl, "--user", "is-active", JOB_UNIT],
        capture_output=True,
        text=True,
        check=False,
    )
    status = result.stdout.strip()
    if result.returncode == 0 and status == "active":
        return True
    if status in {"inactive", "failed", "deactivating"}:
        return False
    return None


def start_job(
    source_text: str,
    mode: str,
    targets_text: str,
    output_format: str,
    profile: str,
) -> int:
    ready, message = engine_ready()
    if not ready:
        raise StemSplitterError(message)
    require_command("ffmpeg")
    systemd_run = require_command("systemd-run")
    source = validate_input(source_text)
    targets = parse_targets(targets_text) if mode == "remove" else ()
    if output_format not in OUTPUT_FORMATS:
        raise StemSplitterError(f"Unsupported output format: {output_format}")
    if profile not in PROCESSING_PROFILES:
        raise StemSplitterError(f"Unsupported processing profile: {profile}")
    if unit_is_active() is True:
        raise StemSplitterError("Another background separation job is already running.")

    lock = operation_lock()
    lock.close()
    job_id = uuid.uuid4().hex
    write_job_state({
        "schemaVersion": 1,
        "jobId": job_id,
        "status": "starting",
        "percent": 2,
        "message": "Starting the background worker…",
        "sourcePath": str(source),
        "sourceName": source.name,
        "mode": mode,
        "targets": list(targets),
        "format": output_format,
        "profile": profile,
        "outputPath": "",
        "startedAt": utc_now(),
    })

    helper = Path(__file__).with_name("stem-tool")
    command = [
        systemd_run,
        "--user",
        "--quiet",
        "--collect",
        f"--unit={JOB_UNIT}",
        "--description=Omarchy Stem Splitter background job",
        "--service-type=exec",
        "--property=KillMode=control-group",
        "--property=SuccessExitStatus=130",
        "--property=TimeoutStopSec=20s",
        "--",
        str(helper),
        "worker",
        "--job-id",
        job_id,
        "--mode",
        mode,
        "--targets",
        ",".join(targets) if targets else "vocals",
        "--format",
        output_format,
        "--profile",
        profile,
        "--",
        str(source),
    ]
    try:
        run_checked(command)
    except StemSplitterError as exc:
        state = load_job_state() or {}
        state.update(status="error", percent=0, message=str(exc), finishedAt=utc_now())
        write_job_state(state)
        raise
    emit("STARTED", job_id)
    return 0


def worker_job(
    job_id: str,
    source_text: str,
    mode: str,
    targets_text: str,
    output_format: str,
    profile: str,
) -> int:
    global ACTIVE_JOB_ID
    state = load_job_state()
    if state is None or state.get("jobId") != job_id:
        raise StemSplitterError("Background job state does not match this worker.")
    ACTIVE_JOB_ID = job_id
    update_job_state(status="working", percent=4, message="Background worker started.")
    return process_track(source_text, mode, targets_text, output_format, profile)


def job_status() -> int:
    state = load_job_state()
    if state is None:
        state = {
            "schemaVersion": 1,
            "status": "idle",
            "percent": 0,
            "message": "Choose a track to begin.",
            "outputPath": "",
        }
    elif state.get("status") in {"starting", "working"} and unit_is_active() is False:
        state.update(
            status="error",
            percent=0,
            message="The background worker stopped unexpectedly. See the last-error log.",
            finishedAt=utc_now(),
        )
        write_job_state(state)
    print(json.dumps(state, separators=(",", ":")), flush=True)
    return 0


def cancel_job() -> int:
    state = load_job_state()
    if state is None or state.get("status") not in {"starting", "working"}:
        emit("IDLE", "No background separation job is running.")
        return 0
    systemctl = require_command("systemctl")
    subprocess.run(
        [systemctl, "--user", "stop", JOB_UNIT],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    state.update(
        status="cancelled",
        percent=0,
        message="Cancelled. No partial output was published.",
        finishedAt=utc_now(),
    )
    write_job_state(state)
    emit("CANCELLED", state["message"])
    return 0


def select_file() -> int:
    zenity = require_command("zenity")
    process = subprocess.run([
        zenity, "--file-selection", "--title=Choose an audio track",
        "--file-filter=Audio files | *.wav *.flac *.mp3 *.m4a *.ogg *.oga *.aac *.wma *.aiff *.aif",
        "--file-filter=All files | *",
    ], text=True, capture_output=True, check=False)
    if process.returncode == 0 and process.stdout.strip():
        print(process.stdout.strip())
        return 0
    return 20


def open_folder(path_text: str) -> int:
    path = Path(path_text).expanduser().resolve()
    if not path.is_dir() or OUTPUT_ROOT.resolve() not in path.parents:
        raise StemSplitterError("Refusing to open a folder outside the Stem Splitter output directory.")
    opener = require_command("xdg-open")
    subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Omarchy Stem Splitter helper")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check")
    subparsers.add_parser("setup")
    subparsers.add_parser("select")
    for command_name in ("run", "start"):
        job_parser = subparsers.add_parser(command_name)
        job_parser.add_argument("--mode", choices=("remove", "full"), required=True)
        job_parser.add_argument("--targets", default="vocals")
        job_parser.add_argument("--format", choices=OUTPUT_FORMATS, default="flac")
        job_parser.add_argument("--profile", choices=PROCESSING_PROFILES, default="best")
        job_parser.add_argument("source")
    worker_parser = subparsers.add_parser("worker")
    worker_parser.add_argument("--job-id", required=True)
    worker_parser.add_argument("--mode", choices=("remove", "full"), required=True)
    worker_parser.add_argument("--targets", default="vocals")
    worker_parser.add_argument("--format", choices=OUTPUT_FORMATS, default="flac")
    worker_parser.add_argument("--profile", choices=PROCESSING_PROFILES, default="best")
    worker_parser.add_argument("source")
    subparsers.add_parser("status")
    subparsers.add_parser("cancel")
    open_parser = subparsers.add_parser("open")
    open_parser.add_argument("path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check":
            ready, message = engine_ready()
            emit("READY" if ready else "MISSING", message)
            return 0 if ready else 1
        if args.command == "setup":
            return setup_engine()
        if args.command == "select":
            return select_file()
        if args.command == "run":
            return process_track(args.source, args.mode, args.targets, args.format, args.profile)
        if args.command == "start":
            return start_job(args.source, args.mode, args.targets, args.format, args.profile)
        if args.command == "worker":
            return worker_job(args.job_id, args.source, args.mode, args.targets, args.format, args.profile)
        if args.command == "status":
            return job_status()
        if args.command == "cancel":
            return cancel_job()
        if args.command == "open":
            return open_folder(args.path)
    except KeyboardInterrupt:
        update_job_state(
            status="cancelled",
            percent=0,
            message="Cancelled. No partial output was published.",
            finishedAt=utc_now(),
        )
        print("Cancelled.", file=sys.stderr)
        return 130
    except (StemSplitterError, OSError, subprocess.SubprocessError) as exc:
        update_job_state(
            status="error",
            percent=0,
            message=str(exc),
            finishedAt=utc_now(),
        )
        print(str(exc), file=sys.stderr)
        return 1
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
