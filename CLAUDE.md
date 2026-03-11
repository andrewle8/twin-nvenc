# twin-nvenc

Dual NVENC batch video compressor. Python CLI tool using asyncio + click + rich.

## Structure

- `src/twin_nvenc/cli.py` — Click CLI entry point, wires scanner -> encoder -> report
- `src/twin_nvenc/scanner.py` — Finds video files, skips already-compressed, ffprobe metadata
- `src/twin_nvenc/encoder.py` — Builds ffmpeg commands, asyncio subprocess with progress parsing
- `src/twin_nvenc/report.py` — Rich-based colored output, stats computation

## Key Design Decisions

- asyncio.Semaphore(n) for parallel encoding — next file starts the instant a chip frees up
- Rate control: `-rc vbr -cq N -b:v 0` (not constqp) for adaptive quality
- Skip-if-bigger: encode to .tmp.mp4, compare sizes, delete if larger than original
- ffmpeg progress parsed via `-progress pipe:1` stdout, not stderr

## Commands

```bash
pip install -e ".[dev]"     # Install
pytest                       # Run tests
twin-nvenc --help           # CLI help
twin-nvenc --dry-run <dir>  # Preview
```

## ffmpeg Location

Not in PATH on this system. Auto-detected at `C:\Program Files\ShareX\ffmpeg.exe`.
