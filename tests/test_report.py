"""Tests for result reporting and stats computation."""

from pathlib import Path

from twin_nvenc.encoder import EncodeResult
from twin_nvenc.report import compute_stats


def _make_result(
    input_name: str = "clip.mp4",
    input_dir: str = "/videos",
    input_size: int = 1_000_000,
    output_size: int = 400_000,
    success: bool = True,
    skipped_bigger: bool = False,
    elapsed: float = 10.0,
) -> EncodeResult:
    return EncodeResult(
        input_path=Path(input_dir) / input_name,
        output_path=Path(input_dir) / "compressed" / input_name,
        input_size=input_size,
        output_size=output_size,
        success=success,
        skipped_bigger=skipped_bigger,
        elapsed_secs=elapsed,
    )


def test_compute_stats_single_folder():
    results = [
        _make_result("a.mp4", "/vids", 1_000_000, 400_000),
        _make_result("b.mp4", "/vids", 2_000_000, 800_000),
    ]
    stats = compute_stats(results)
    assert len(stats) == 1
    folder = stats[0]
    assert folder.total_input == 3_000_000
    assert folder.total_output == 1_200_000
    assert folder.file_count == 2
    assert folder.saved_bytes == 1_800_000


def test_compute_stats_multiple_folders():
    results = [
        _make_result("a.mp4", "/dir1", 1_000_000, 400_000),
        _make_result("b.mp4", "/dir2", 2_000_000, 800_000),
    ]
    stats = compute_stats(results)
    assert len(stats) == 2


def test_compute_stats_skips_failures():
    results = [
        _make_result("a.mp4", "/vids", 1_000_000, 400_000, success=True),
        _make_result("b.mp4", "/vids", 2_000_000, 0, success=False),
    ]
    stats = compute_stats(results)
    assert stats[0].file_count == 1
    assert stats[0].total_input == 1_000_000


def test_compute_stats_skips_bigger():
    results = [
        _make_result("a.mp4", "/vids", 1_000_000, 1_100_000, skipped_bigger=True),
    ]
    stats = compute_stats(results)
    assert len(stats) == 0
