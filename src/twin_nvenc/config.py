"""TOML config file loading and preset merging."""

from __future__ import annotations

import sys
import tomllib
from dataclasses import fields
from pathlib import Path

from twin_nvenc.encoder import EncoderConfig

if sys.platform == "win32":
    _CONFIG_DIR = Path.home() / ".config" / "twin-nvenc"
else:
    _CONFIG_DIR = Path.home() / ".config" / "twin-nvenc"

CONFIG_PATH = _CONFIG_DIR / "config.toml"

# Map TOML key names to EncoderConfig field names
_KEY_MAP = {
    "codec": "codec",
    "preset": "preset",
    "quality": "quality",
    "audio": "audio_bitrate",
    "parallel": "parallel",
    "output": "output_dir",
    "ffmpeg": "ffmpeg_path",
}

DEFAULT_CONFIG_TOML = """\
# twin-nvenc configuration
# Place at: ~/.config/twin-nvenc/config.toml

[defaults]
codec = "av1_nvenc"
preset = "p4"
quality = 28
audio = "128k"
parallel = 2
output = "compressed"
# ffmpeg = "C:\\\\Program Files\\\\ShareX\\\\ffmpeg.exe"

# Named presets - use with: twin-nvenc -P screen <dirs>
# CLI flags always override preset values.

[presets.screen]
quality = 26
# Sharp text, UI elements — lower CQ preserves detail

[presets.gaming]
quality = 32
preset = "p4"
# Fast action barely compresses; don't waste time on slow presets

[presets.archival]
preset = "p7"
quality = 24
# Maximum quality, slow — good for overnight batches

[presets.hevc]
codec = "hevc_nvenc"
quality = 26
# HEVC for broader device compatibility

[presets.fast]
preset = "p1"
quality = 32
# Fastest possible encode, larger files
"""


def load_config() -> dict:
    """Load config.toml if it exists. Returns raw dict."""
    if not CONFIG_PATH.is_file():
        return {}
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def init_config() -> Path:
    """Create default config.toml. Returns path."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    return CONFIG_PATH


def resolve_config(
    profile: str | None = None,
    cli_overrides: dict[str, object] | None = None,
) -> EncoderConfig:
    """Build EncoderConfig by layering: defaults < config.toml defaults < preset < CLI flags."""
    config = EncoderConfig()
    raw = load_config()

    # Apply [defaults] from config.toml
    if "defaults" in raw:
        _apply_section(config, raw["defaults"])

    # Apply [presets.<name>] on top
    if profile and "presets" in raw:
        presets = raw["presets"]
        if profile not in presets:
            available = ", ".join(presets.keys()) if presets else "none"
            raise ValueError(
                f"Unknown profile '{profile}'. Available: {available}"
            )
        _apply_section(config, presets[profile])

    # Apply CLI overrides last (highest priority)
    if cli_overrides:
        _apply_overrides(config, cli_overrides)

    return config


def list_profiles() -> list[str]:
    """Return available profile names from config.toml."""
    raw = load_config()
    if "presets" in raw:
        return list(raw["presets"].keys())
    return []


def _apply_section(config: EncoderConfig, section: dict) -> None:
    """Apply a TOML section's values to an EncoderConfig."""
    for toml_key, value in section.items():
        field_name = _KEY_MAP.get(toml_key)
        if field_name and hasattr(config, field_name):
            setattr(config, field_name, value)


def _apply_overrides(config: EncoderConfig, overrides: dict[str, object]) -> None:
    """Apply CLI overrides — only non-default values."""
    for field_name, value in overrides.items():
        if value is not None and hasattr(config, field_name):
            setattr(config, field_name, value)
