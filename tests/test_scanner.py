"""Tests for video file scanning and metadata."""

from pathlib import Path

from twin_nvenc.scanner import FileInfo, find_videos


def test_find_videos_discovers_all_extensions(tmp_video_dir: Path):
    """Should find .mp4, .mkv, .avi files."""
    files = find_videos([tmp_video_dir], output_dir="compressed")
    assert len(files) == 3
    extensions = {f.input_path.suffix for f in files}
    assert extensions == {".mp4", ".mkv", ".avi"}


def test_find_videos_skips_already_compressed(tmp_video_dir_with_compressed: Path):
    """Should skip clip1.mp4 since compressed/clip1.mp4 exists."""
    files = find_videos([tmp_video_dir_with_compressed], output_dir="compressed")
    names = {f.input_path.name for f in files}
    assert "clip1.mp4" not in names
    assert len(files) == 2


def test_find_videos_creates_output_dir(tmp_video_dir: Path):
    """Should create the compressed/ subdirectory."""
    find_videos([tmp_video_dir], output_dir="compressed")
    assert (tmp_video_dir / "compressed").is_dir()


def test_find_videos_skips_missing_dirs(tmp_path: Path):
    """Should skip directories that don't exist without crashing."""
    files = find_videos([tmp_path / "nonexistent"], output_dir="compressed")
    assert files == []


def test_find_videos_output_paths_are_mp4(tmp_video_dir: Path):
    """All output files should be .mp4 regardless of input extension."""
    files = find_videos([tmp_video_dir], output_dir="compressed")
    for f in files:
        assert f.output_path.suffix == ".mp4"


def test_fileinfo_has_size(tmp_video_dir: Path):
    """FileInfo should capture the input file size."""
    files = find_videos([tmp_video_dir], output_dir="compressed")
    for f in files:
        assert f.size_bytes == 1024


def test_find_videos_multiple_dirs(tmp_path: Path):
    """Should scan multiple input directories."""
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()
    (dir1 / "a.mp4").write_bytes(b"\x00" * 100)
    (dir2 / "b.mp4").write_bytes(b"\x00" * 100)
    files = find_videos([dir1, dir2], output_dir="compressed")
    assert len(files) == 2
