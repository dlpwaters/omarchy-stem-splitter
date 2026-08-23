# Changelog

All notable changes to Stem Splitter are documented here. This project follows [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-08-23

### Security

- Replaced live transitive dependency resolution with a complete SHA-256 requirements lock
- Pinned and hash-locked the isolated build toolchain for the sole source-only dependency
- Bound setup to the reviewed CPython 3.12.13 x86_64 build and exact package environment
- Added exact URL, byte-size, and SHA-256 locks for every supported model, config, metadata file, and Demucs weight
- Verify every model component before Audio Separator can load it; changed upstream bytes fail closed

## [1.0.1] - 2026-08-20

### Added

- Durable transient user-service jobs that survive panel closure and Omarchy Shell restarts
- Persistent progress and automatic UI reconnection to an active job
- Fast MDX-Net/HTDemucs profile alongside the original best-quality models

### Fixed

- Prevented detached orphan workers when the QML process wrapper disappears
- Added control-group cancellation and single-job enforcement
- Replaced long silent inference periods with model-derived progress updates
- Pinned a matching CPU `torchvision` build for reliable Fast-profile startup

## [1.0.0] - 2026-08-20

### Added

- Selective removal of vocals, drums, bass, other instruments, or valid combinations
- Full vocals/drums/bass/other stem separation
- BS-RoFormer vocal removal and fine-tuned HTDemucs four-stem processing
- FLAC, 16-bit PCM WAV, and AAC-LC MP4 output
- Non-overwriting Desktop output folders with per-job metadata
- Isolated, pinned CPU engine setup with cancellation and staged publishing
- Omarchy bar panel, typed IPC, live progress, and output-folder access

[1.0.0]: https://github.com/dlpwaters/omarchy-stem-splitter/releases/tag/v1.0.0
[1.0.1]: https://github.com/dlpwaters/omarchy-stem-splitter/compare/v1.0.0...v1.0.1
[1.1.0]: https://github.com/dlpwaters/omarchy-stem-splitter/compare/v1.0.1...v1.1.0
