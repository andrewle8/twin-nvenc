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
@click.argument("input_dirs", nargs=-1, required=False, type=click.Path(exists=False))
@click.option(
    "-c", "--codec", default=None,
    help="Encoder: av1_nvenc, hevc_nvenc, h264_nvenc",
)
@click.option(
    "-p", "--preset", default=None,
    help="NVENC preset: p1 (fastest) to p7 (slowest/best)",
)
@click.option(
    "-q", "--quality", default=None, type=int,
    help="Constant quality (CQ): 0-51, higher=smaller/worse",
)
@click.option("-a", "--audio", default=None, help="Audio bitrate")
@click.option(
    "-j", "--parallel", default=None, type=int,
    help="Parallel encodes (match NVENC chip count)",
)
@click.option("-o", "--output", default=None, help="Output subdirectory name")
@click.option(
    "-f", "--ffmpeg", "ffmpeg_path", default=None,
    help="Path to ffmpeg binary",
)
@click.option(
    "-P", "--profile", default=None,
    help="Use a named preset from config.toml (e.g. screen, gaming, archival)",
)
@click.option("--dry-run", is_flag=True, help="Show what would be encoded")
@click.option("--tui", is_flag=True, help="Launch interactive TUI dashboard")
@click.option("--demo", is_flag=True, help="Launch TUI with simulated encoding (preview)")
@click.option("--init-config", is_flag=True, help="Create default config.toml")
@click.option("--list-profiles", is_flag=True, help="List available profiles")
def main(
    input_dirs: tuple[str, ...],
    codec: str | None,
    preset: str | None,
    quality: int | None,
    audio: str | None,
    parallel: int | None,
    output: str | None,
    ffmpeg_path: str | None,
    profile: str | None,
    dry_run: bool,
    tui: bool,
    demo: bool,
    init_config: bool,
    list_profiles: bool,
) -> None:
    """Batch compress video files using NVIDIA NVENC hardware encoding.

    Leverages dual NVENC chips (RTX 4090) for parallel encoding.
    Skips files that already exist in the output directory -- safe to interrupt and resume.

    \b
    Examples:
      twin-nvenc "F:/OBS Captures/My Videos"
      twin-nvenc -P screen "F:/OBS Captures"
      twin-nvenc -c hevc_nvenc -p p7 -q 24 /path/to/videos
      twin-nvenc -j 1 /path/to/videos
      twin-nvenc --init-config
    """
    from twin_nvenc.config import (
        CONFIG_PATH,
        init_config as do_init_config,
        list_profiles as do_list_profiles,
        resolve_config,
    )

    # Handle config management commands
    if init_config:
        path = do_init_config()
        console.print(f"[green]Config created:[/] {path}")
        return

    if list_profiles:
        profiles = do_list_profiles()
        if profiles:
            console.print("[bold]Available profiles:[/]")
            for p in profiles:
                console.print(f"  {p}")
        else:
            console.print(
                f"[yellow]No profiles found.[/] Run [bold]twin-nvenc --init-config[/] "
                f"to create {CONFIG_PATH}"
            )
        return

    if not input_dirs:
        console.print("[red]ERROR: No input directories specified[/]")
        console.print("Usage: twin-nvenc [OPTIONS] <input-dir> [input-dir2] ...")
        sys.exit(1)

    # Build config: config.toml defaults < profile < CLI flags
    cli_overrides = {}
    if codec is not None:
        cli_overrides["codec"] = codec
    if preset is not None:
        cli_overrides["preset"] = preset
    if quality is not None:
        cli_overrides["quality"] = quality
    if audio is not None:
        cli_overrides["audio_bitrate"] = audio
    if parallel is not None:
        cli_overrides["parallel"] = parallel
    if output is not None:
        cli_overrides["output_dir"] = output

    try:
        config = resolve_config(profile=profile, cli_overrides=cli_overrides or None)
    except ValueError as e:
        console.print(f"[red]ERROR: {e}[/]")
        sys.exit(1)

    # Resolve ffmpeg (CLI flag > config > auto-detect)
    if ffmpeg_path:
        if not Path(ffmpeg_path).is_file():
            console.print(f"[red]ERROR: ffmpeg not found at: {ffmpeg_path}[/]")
            sys.exit(1)
        config.ffmpeg_path = ffmpeg_path
    elif config.ffmpeg_path == "ffmpeg":
        config.ffmpeg_path = _find_ffmpeg()

    config.dry_run = dry_run

    print_banner(config)

    if profile:
        console.print(f"  [cyan]Profile:[/]  {profile}")
        console.print()

    # Scan for files
    dirs = [Path(d) for d in input_dirs]
    file_infos = find_videos(dirs, output_dir=config.output_dir)

    if not file_infos:
        console.print("[green]Nothing to do -- all files already compressed.[/]")
        return

    console.print(f"[bold]Files to encode: {len(file_infos)}[/]")
    console.print()

    # Pre-scan durations (ffprobe -> ffmpeg fallback)
    ffprobe_path = _find_ffprobe(config.ffmpeg_path)
    for fi in file_infos:
        probe_duration(fi, ffprobe_path, config.ffmpeg_path)

    # Build file tuples for encoder
    file_tuples = [
        (fi.input_path, fi.output_path, fi.size_bytes, fi.duration_secs)
        for fi in file_infos
    ]

    if dry_run:
        print_dry_run(file_tuples)
        return

    if tui or demo:
        from twin_nvenc.tui import run_tui

        run_tui(file_infos, config, demo=demo)
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
