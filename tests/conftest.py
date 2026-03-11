"""Shared test fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_video_dir(tmp_path: Path) -> Path:
    """Create a temp directory with fake video files (empty files with video extensions)."""
    for name in ["clip1.mp4", "clip2.mkv", "clip3.avi"]:
        (tmp_path / name).write_bytes(b"\x00" * 1024)
    return tmp_path


@pytest.fixture
def tmp_video_dir_with_compressed(tmp_video_dir: Path) -> Path:
    """Temp dir where clip1 already has a compressed version."""
    compressed = tmp_video_dir / "compressed"
    compressed.mkdir()
    (compressed / "clip1.mp4").write_bytes(b"\x00" * 512)
    return tmp_video_dir
