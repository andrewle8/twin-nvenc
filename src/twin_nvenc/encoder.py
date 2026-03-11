"""ffmpeg NVENC encoding with progress parsing."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class EncoderConfig:
    """Encoding configuration."""

    codec: str = "av1_nvenc"
    preset: str = "p4"
    quality: int = 28
    audio_bitrate: str = "128k"
    parallel: int = 2
    output_dir: str = "compressed"
    ffmpeg_path: str = "ffmpeg"
    dry_run: bool = False


@dataclass
class EncodeResult:
    """Result of encoding a single file."""

    input_path: Path
    output_path: Path
    input_size: int
    output_size: int = 0
    elapsed_secs: float = 0.0
    success: bool = False
    skipped_bigger: bool = False
    error: str | None = None

    @property
    def ratio(self) -> int | None:
        """Compression ratio as percentage (50 = half size)."""
        if self.input_size > 0 and self.output_size > 0:
            return round(self.output_size * 100 / self.input_size)
        return None


def build_ffmpeg_cmd(
    input_path: Path,
    output_path: Path,
    config: EncoderConfig,
) -> list[str]:
    """Build the ffmpeg command with optimal NVENC flags."""
    return [
        config.ffmpeg_path,
        "-hide_banner",
        "-hwaccel", "cuda",
        "-hwaccel_output_format", "cuda",
        "-i", str(input_path),
        "-c:v", config.codec,
        "-preset", config.preset,
        "-rc", "vbr",
        "-cq", str(config.quality),
        "-b:v", "0",
        "-multipass", "fullres",
        "-rc-lookahead", "32",
        "-spatial-aq", "1",
        "-temporal-aq", "1",
        "-bf", "3",
        "-b_adapt", "1",
        "-c:a", "aac",
        "-b:a", config.audio_bitrate,
        "-progress", "pipe:1",
        "-nostats",
        str(output_path),
        "-y",
    ]


def parse_progress_block(
    block: dict[str, str],
    total_duration: float | None,
) -> dict:
    """Parse an ffmpeg progress key-value block into useful metrics."""
    result: dict = {"percent": None, "speed": None, "eta_secs": None}

    raw_speed = block.get("speed", "N/A")
    result["speed"] = raw_speed

    out_time_us = block.get("out_time_us")
    if out_time_us is not None:
        try:
            current_secs = int(out_time_us) / 1_000_000
        except ValueError:
            return result

        if total_duration and total_duration > 0:
            result["percent"] = round(current_secs / total_duration * 100, 1)

            # Parse speed multiplier for ETA
            speed_val = _parse_speed(raw_speed)
            if speed_val and speed_val > 0:
                remaining = total_duration - current_secs
                result["eta_secs"] = round(remaining / speed_val, 1)

    return result


def _parse_speed(speed_str: str) -> float | None:
    """Parse '2.5x' into 2.5."""
    if not speed_str or speed_str == "N/A":
        return None
    try:
        return float(speed_str.rstrip("x"))
    except ValueError:
        return None


async def encode_file(
    input_path: Path,
    output_path: Path,
    input_size: int,
    duration_secs: float | None,
    config: EncoderConfig,
    on_progress: Callable[[dict], None] | None = None,
) -> EncodeResult:
    """Encode a single file using ffmpeg. Returns EncodeResult."""
    tmp_output = output_path.with_suffix(".tmp.mp4")
    cmd = build_ffmpeg_cmd(input_path, tmp_output, config)
    start = time.monotonic()

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        block: dict[str, str] = {}
        assert proc.stdout is not None

        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if "=" in line:
                key, _, val = line.partition("=")
                block[key] = val

            if line.startswith("progress="):
                if on_progress:
                    progress = parse_progress_block(block, duration_secs)
                    on_progress(progress)
                block = {}

        await proc.wait()
        elapsed = time.monotonic() - start

        if proc.returncode != 0:
            tmp_output.unlink(missing_ok=True)
            stderr_out = ""
            if proc.stderr:
                stderr_out = (await proc.stderr.read()).decode(errors="replace")
            return EncodeResult(
                input_path=input_path,
                output_path=output_path,
                input_size=input_size,
                elapsed_secs=elapsed,
                error=stderr_out[:500] if stderr_out else "ffmpeg exited with error",
            )

        output_size = tmp_output.stat().st_size

        # Skip-if-bigger: delete output if it's larger than original
        if output_size >= input_size:
            tmp_output.unlink(missing_ok=True)
            return EncodeResult(
                input_path=input_path,
                output_path=output_path,
                input_size=input_size,
                output_size=output_size,
                elapsed_secs=elapsed,
                success=True,
                skipped_bigger=True,
            )

        # Atomic rename from .tmp.mp4 to final name
        tmp_output.rename(output_path)

        return EncodeResult(
            input_path=input_path,
            output_path=output_path,
            input_size=input_size,
            output_size=output_size,
            elapsed_secs=elapsed,
            success=True,
        )

    except Exception as exc:
        tmp_output.unlink(missing_ok=True)
        return EncodeResult(
            input_path=input_path,
            output_path=output_path,
            input_size=input_size,
            elapsed_secs=time.monotonic() - start,
            error=str(exc),
        )


async def encode_batch(
    files: list[tuple[Path, Path, int, float | None]],
    config: EncoderConfig,
    on_file_start: Callable[[int, int, Path], None] | None = None,
    on_file_done: Callable[[int, int, EncodeResult], None] | None = None,
    on_progress: Callable[[int, dict], None] | None = None,
) -> list[EncodeResult]:
    """Encode all files with semaphore-limited parallelism.

    files: list of (input_path, output_path, size_bytes, duration_secs)
    """
    semaphore = asyncio.Semaphore(config.parallel)
    counter = 0
    lock = asyncio.Lock()
    total = len(files)

    async def _encode_one(
        input_path: Path,
        output_path: Path,
        size: int,
        duration: float | None,
    ) -> EncodeResult:
        nonlocal counter
        async with semaphore:
            async with lock:
                counter += 1
                idx = counter
            if on_file_start:
                on_file_start(idx, total, input_path)

            def _progress_cb(progress: dict) -> None:
                if on_progress:
                    on_progress(idx, progress)

            result = await encode_file(
                input_path, output_path, size, duration, config, _progress_cb
            )

            if on_file_done:
                on_file_done(idx, total, result)
            return result

    tasks = [
        _encode_one(inp, out, sz, dur)
        for inp, out, sz, dur in files
    ]
    results = await asyncio.gather(*tasks)
    return list(results)
