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


def probe_duration(
    file_info: FileInfo,
    ffprobe_path: str = "ffprobe",
    ffmpeg_path: str = "ffmpeg",
) -> None:
    """Get video duration via ffprobe, falling back to ffmpeg. Mutates file_info in place."""
    # Try ffprobe first (structured JSON output)
    if _probe_with_ffprobe(file_info, ffprobe_path):
        return
    # Fall back to parsing ffmpeg -i stderr (Duration: HH:MM:SS.xx)
    _probe_with_ffmpeg(file_info, ffmpeg_path)


def _probe_with_ffprobe(file_info: FileInfo, ffprobe_path: str) -> bool:
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
            return True
    except (subprocess.TimeoutExpired, KeyError, ValueError, FileNotFoundError):
        pass
    return False


def _probe_with_ffmpeg(file_info: FileInfo, ffmpeg_path: str) -> bool:
    """Parse duration from ffmpeg -i stderr: 'Duration: 00:05:23.45, ...'"""
    import re

    try:
        result = subprocess.run(
            [ffmpeg_path, "-i", str(file_info.input_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # ffmpeg -i always exits non-zero (no output file), parse stderr
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
        if match:
            h, m, s, frac = match.groups()
            file_info.duration_secs = (
                int(h) * 3600 + int(m) * 60 + int(s) + int(frac) / 100
            )
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False
