"""Tests for config loading and preset merging."""

from pathlib import Path

import pytest

from twin_nvenc.config import resolve_config, init_config, load_config, list_profiles
from twin_nvenc.encoder import EncoderConfig


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override config path to a temp directory."""
    import twin_nvenc.config as cfg

    config_path = tmp_path / "config.toml"
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_path)
    monkeypatch.setattr(cfg, "_CONFIG_DIR", tmp_path)
    return tmp_path


def test_resolve_config_no_file(config_dir: Path):
    """Without config.toml, should return defaults."""
    config = resolve_config()
    assert config.codec == "av1_nvenc"
    assert config.quality == 28
    assert config.preset == "p4"


def test_resolve_config_with_defaults(config_dir: Path):
    """[defaults] section should override EncoderConfig defaults."""
    (config_dir / "config.toml").write_text(
        '[defaults]\nquality = 24\npreset = "p7"\n'
    )
    config = resolve_config()
    assert config.quality == 24
    assert config.preset == "p7"
    assert config.codec == "av1_nvenc"  # unchanged


def test_resolve_config_with_profile(config_dir: Path):
    """Profile should layer on top of defaults."""
    (config_dir / "config.toml").write_text(
        '[defaults]\nquality = 28\n\n[presets.screen]\nquality = 22\n'
    )
    config = resolve_config(profile="screen")
    assert config.quality == 22


def test_resolve_config_cli_overrides_profile(config_dir: Path):
    """CLI flags should override profile values."""
    (config_dir / "config.toml").write_text(
        '[defaults]\nquality = 28\n\n[presets.screen]\nquality = 22\n'
    )
    config = resolve_config(
        profile="screen",
        cli_overrides={"quality": 18},
    )
    assert config.quality == 18


def test_resolve_config_unknown_profile(config_dir: Path):
    """Unknown profile should raise ValueError."""
    (config_dir / "config.toml").write_text(
        '[presets.screen]\nquality = 22\n'
    )
    with pytest.raises(ValueError, match="Unknown profile 'bogus'"):
        resolve_config(profile="bogus")


def test_init_config(config_dir: Path):
    """init_config should create config.toml with presets."""
    path = init_config()
    assert path.is_file()
    content = path.read_text()
    assert "[defaults]" in content
    assert "[presets.screen]" in content
    assert "[presets.gaming]" in content
    assert "[presets.archival]" in content


def test_list_profiles(config_dir: Path):
    """Should return preset names from config."""
    init_config()
    profiles = list_profiles()
    assert "screen" in profiles
    assert "gaming" in profiles
    assert "archival" in profiles


def test_list_profiles_no_file(config_dir: Path):
    """No config file should return empty list."""
    assert list_profiles() == []


def test_resolve_config_ffmpeg_override(config_dir: Path):
    """ffmpeg key should map to ffmpeg_path field."""
    (config_dir / "config.toml").write_text(
        '[defaults]\nffmpeg = "C:\\\\ffmpeg.exe"\n'
    )
    config = resolve_config()
    assert config.ffmpeg_path == "C:\\ffmpeg.exe"


def test_resolve_config_audio_mapping(config_dir: Path):
    """audio key should map to audio_bitrate field."""
    (config_dir / "config.toml").write_text(
        '[defaults]\naudio = "192k"\n'
    )
    config = resolve_config()
    assert config.audio_bitrate == "192k"
