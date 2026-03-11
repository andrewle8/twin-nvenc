"""Find video files and gather metadata."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv"}


@dataclass
class FileInfo:
    """A video file to be encoded."""

    input_path: Path
    output_path: Path
    size_bytes: int
    duration_secs: float | None = None  # populated by probe_duration


def find_videos(
    input_dirs: list[Path],
    output_dir: str = "compressed",
) -> list[FileInfo]:
    """Discover video files across input directories, skipping already-compressed."""
    files: list[FileInfo] = []

    for dir_path in input_dirs:
        if not dir_path.is_dir():
            continue

        out_path = dir_path / output_dir
        out_path.mkdir(exist_ok=True)

        for child in sorted(dir_path.iterdir()):
            if not child.is_file():
                continue
            if child.suffix.lower() not in VIDEO_EXTENSIONS:
                continue

            output_file = out_path / f"{child.stem}.mp4"
            if output_file.exists():
                continue

            files.append(
                FileInfo(
                    input_path=child,
                    output_path=output_file,
                    size_bytes=child.stat().st_size,
                )
            )

    return files


def probe_duration(file_info: FileInfo, ffprobe_path: str = "ffprobe") -> None:
    """Use ffprobe to get video duration. Mutates file_info.duration_secs in place."""
    try:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                str(file_info.input_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            file_info.duration_secs = float(data["format"]["duration"])
    except (subprocess.TimeoutExpired, KeyError, ValueError, FileNotFoundError):
        pass
