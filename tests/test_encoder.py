"""Tests for encoding logic and progress parsing."""

from pathlib import Path

from twin_nvenc.encoder import (
    EncodeResult,
    EncoderConfig,
    build_ffmpeg_cmd,
    parse_progress_block,
)


def test_build_ffmpeg_cmd_default():
    """Default command should use optimal AV1 NVENC flags."""
    config = EncoderConfig()
    cmd = build_ffmpeg_cmd(Path("/in/video.mp4"), Path("/out/video.mp4"), config)

    assert cmd[0] == config.ffmpeg_path
    assert "-hwaccel" in cmd
    assert "cuda" in cmd
    assert "-hwaccel_output_format" in cmd
    idx = cmd.index("-rc")
    assert cmd[idx + 1] == "vbr"
    assert "-cq" in cmd
    assert "-multipass" in cmd
    assert "-rc-lookahead" in cmd
    assert "-spatial-aq" in cmd
    assert "-temporal-aq" in cmd
    assert "-progress" in cmd
    assert "pipe:1" in cmd


def test_build_ffmpeg_cmd_custom_codec():
    """Should respect custom codec setting."""
    config = EncoderConfig(codec="hevc_nvenc")
    cmd = build_ffmpeg_cmd(Path("/in/v.mp4"), Path("/out/v.mp4"), config)
    assert "hevc_nvenc" in cmd


def test_build_ffmpeg_cmd_custom_quality():
    """Should use custom quality value in -cq flag."""
    config = EncoderConfig(quality=24)
    cmd = build_ffmpeg_cmd(Path("/in/v.mp4"), Path("/out/v.mp4"), config)
    idx = cmd.index("-cq")
    assert cmd[idx + 1] == "24"


def test_parse_progress_block_valid():
    """Should extract time and speed from ffmpeg progress output."""
    block = {
        "out_time_us": "5000000",
        "speed": "2.5x",
        "frame": "150",
    }
    progress = parse_progress_block(block, total_duration=10.0)
    assert progress["percent"] == 50.0
    assert progress["speed"] == "2.5x"
    assert progress["eta_secs"] == 2.0  # 5s remaining / 2.5x speed


def test_parse_progress_block_no_duration():
    """Should return None percent when total duration unknown."""
    block = {"out_time_us": "5000000", "speed": "2.0x"}
    progress = parse_progress_block(block, total_duration=None)
    assert progress["percent"] is None


def test_parse_progress_block_zero_speed():
    """Should handle 0x or N/A speed gracefully."""
    block = {"out_time_us": "1000000", "speed": "N/A"}
    progress = parse_progress_block(block, total_duration=10.0)
    assert progress["eta_secs"] is None


def test_encoder_config_defaults():
    """Default config should match our researched optimal settings."""
    config = EncoderConfig()
    assert config.codec == "av1_nvenc"
    assert config.preset == "p4"
    assert config.quality == 28
    assert config.audio_bitrate == "128k"
    assert config.parallel == 2


def test_encode_result_ratio():
    """Ratio should be output/input as percentage."""
    result = EncodeResult(
        input_path=Path("/in/v.mp4"),
        output_path=Path("/out/v.mp4"),
        input_size=1_000_000,
        output_size=400_000,
        success=True,
    )
    assert result.ratio == 40


def test_encode_result_ratio_none_when_no_output():
    """Ratio should be None when output_size is 0."""
    result = EncodeResult(
        input_path=Path("/in/v.mp4"),
        output_path=Path("/out/v.mp4"),
        input_size=1_000_000,
    )
    assert result.ratio is None
