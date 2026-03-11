"""CLI entry point using Click."""

from __future__ import annotations

import asyncio
import shutil
import sys
import time
from pathlib import Path

import click
from rich.console import Console

from twin_nvenc.encoder import EncodeResult, EncoderConfig, encode_batch
from twin_nvenc.report import (
    print_banner,
    print_dry_run,
    print_file_result,
    print_summary,
)
from twin_nvenc.scanner import find_videos, probe_duration

console = Console()

# Windows-native paths for subprocess calls
_FFMPEG_SEARCH_PATHS_WIN = [
    r"C:\Program Files\ShareX\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\tools\ffmpeg\bin\ffmpeg.exe",
    r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
]


def _find_ffmpeg() -> str:
    """Auto-detect ffmpeg location."""
    if shutil.which("ffmpeg"):
        return "ffmpeg"

    for path in _FFMPEG_SEARCH_PATHS_WIN:
        if Path(path).is_file():
            return path

    console.print("[red]ERROR: ffmpeg not found. Install it or use --ffmpeg <path>[/]")
    sys.exit(1)


def _find_ffprobe(ffmpeg_path: str) -> str:
    """Derive ffprobe path from ffmpeg path."""
    if ffmpeg_path == "ffmpeg":
        return "ffprobe"
    p = Path(ffmpeg_path)
    probe = p.parent / p.name.replace("ffmpeg", "ffprobe")
    if probe.is_file():
        return str(probe)
    return "ffprobe"


@click.command()
@click.argument("input_dirs", nargs=-1, required=True, type=click.Path(exists=False))
@click.option(
    "-c", "--codec", default="av1_nvenc",
    help="Encoder: av1_nvenc, hevc_nvenc, h264_nvenc",
)
@click.option(
    "-p", "--preset", default="p4",
    help="NVENC preset: p1 (fastest) to p7 (slowest/best)",
)
@click.option(
    "-q", "--quality", default=28, type=int,
    help="Constant quality (CQ): 0-51, higher=smaller/worse",
)
@click.option("-a", "--audio", default="128k", help="Audio bitrate")
@click.option(
    "-j", "--parallel", default=2, type=int,
    help="Parallel encodes (match NVENC chip count)",
)
@click.option("-o", "--output", default="compressed", help="Output subdirectory name")
@click.option(
    "-f", "--ffmpeg", "ffmpeg_path", default=None,
    help="Path to ffmpeg binary",
)
@click.option("--dry-run", is_flag=True, help="Show what would be encoded")
def main(
    input_dirs: tuple[str, ...],
    codec: str,
    preset: str,
    quality: int,
    audio: str,
    parallel: int,
    output: str,
    ffmpeg_path: str | None,
    dry_run: bool,
) -> None:
    """Batch compress video files using NVIDIA NVENC hardware encoding.

    Leverages dual NVENC chips (RTX 4090) for parallel encoding.
    Skips files that already exist in the output directory — safe to interrupt and resume.

    \b
    Examples:
      twin-nvenc "F:/OBS Captures/My Videos"
      twin-nvenc -c hevc_nvenc -p p7 -q 24 /path/to/videos
      twin-nvenc -j 1 /path/to/videos
    """
    # Resolve ffmpeg
    resolved_ffmpeg = ffmpeg_path or _find_ffmpeg()
    if ffmpeg_path and not Path(ffmpeg_path).is_file():
        console.print(f"[red]ERROR: ffmpeg not found at: {ffmpeg_path}[/]")
        sys.exit(1)

    config = EncoderConfig(
        codec=codec,
        preset=preset,
        quality=quality,
        audio_bitrate=audio,
        parallel=parallel,
        output_dir=output,
        ffmpeg_path=resolved_ffmpeg,
        dry_run=dry_run,
    )

    print_banner(config)

    # Scan for files
    dirs = [Path(d) for d in input_dirs]
    file_infos = find_videos(dirs, output_dir=output)

    if not file_infos:
        console.print("[green]Nothing to do — all files already compressed.[/]")
        return

    console.print(f"[bold]Files to encode: {len(file_infos)}[/]")
    console.print()

    # Pre-scan durations with ffprobe
    ffprobe_path = _find_ffprobe(resolved_ffmpeg)
    for fi in file_infos:
        probe_duration(fi, ffprobe_path)

    # Build file tuples for encoder
    file_tuples = [
        (fi.input_path, fi.output_path, fi.size_bytes, fi.duration_secs)
        for fi in file_infos
    ]

    if dry_run:
        print_dry_run(file_tuples)
        return

    # Callbacks
    def on_start(idx: int, total: int, path: Path) -> None:
        console.print(f"  [bold dim]\\[{idx}/{total}][/] Encoding: {path.name}...")

    def on_done(idx: int, total: int, result: EncodeResult) -> None:
        print_file_result(idx, total, result)

    # Run the batch
    start = time.monotonic()
    results = asyncio.run(
        encode_batch(file_tuples, config, on_file_start=on_start, on_file_done=on_done)
    )
    elapsed = time.monotonic() - start

    print_summary(results, elapsed, config)


if __name__ == "__main__":
    main()
