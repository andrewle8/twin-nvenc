"""Result reporting with Rich colored output."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from twin_nvenc.encoder import EncodeResult, EncoderConfig

console = Console()


@dataclass
class FolderStats:
    """Aggregated stats for one input directory."""

    folder_name: str
    file_count: int
    total_input: int
    total_output: int

    @property
    def ratio(self) -> int:
        if self.total_input > 0:
            return round(self.total_output * 100 / self.total_input)
        return 0

    @property
    def saved_bytes(self) -> int:
        return self.total_input - self.total_output


def compute_stats(results: list[EncodeResult]) -> list[FolderStats]:
    """Aggregate results by input directory."""
    folders: dict[str, FolderStats] = {}

    for r in results:
        if not r.success or r.skipped_bigger:
            continue
        folder = str(r.input_path.parent)
        if folder not in folders:
            folders[folder] = FolderStats(
                folder_name=r.input_path.parent.name,
                file_count=0,
                total_input=0,
                total_output=0,
            )
        s = folders[folder]
        s.file_count += 1
        s.total_input += r.input_size
        s.total_output += r.output_size

    return list(folders.values())


def _ratio_color(pct: int) -> str:
    """Color based on compression ratio."""
    if pct >= 100:
        return "red"
    if pct >= 80:
        return "yellow"
    return "green"


def _mb(n: int) -> str:
    return f"{n // 1_048_576}MB"


def _gb(n: int) -> str:
    return f"{n // 1_073_741_824}GB"


def print_banner(config: EncoderConfig) -> None:
    """Print startup banner with encoding settings."""
    console.print()
    console.rule("[bold]twin-nvenc — Video Compressor[/bold]", style="bold")
    console.print()
    console.print(f"  [cyan]Codec:[/]    {config.codec}")
    console.print(f"  [cyan]Preset:[/]   {config.preset}")
    console.print(f"  [cyan]Quality:[/]  CQ {config.quality}")
    console.print(f"  [cyan]Audio:[/]    {config.audio_bitrate}")
    console.print(f"  [cyan]Parallel:[/] {config.parallel} encodes")
    console.print(f"  [cyan]ffmpeg:[/]   {config.ffmpeg_path}")
    console.print()


def print_file_result(idx: int, total: int, result: EncodeResult) -> None:
    """Print a single file's encode result."""
    name = result.input_path.name
    elapsed = f"{result.elapsed_secs:.0f}s"

    if not result.success:
        console.print(
            f"  [bold]\\[{idx}/{total}][/] [red]ERROR:[/] {name} — {result.error}"
        )
        return

    if result.skipped_bigger:
        ratio = result.ratio or 100
        console.print(
            f"  [bold]\\[{idx}/{total}][/] {name} — "
            f"{_mb(result.input_size)} → {_mb(result.output_size)} "
            f"([red]{ratio}%[/]) — [yellow]SKIPPED (bigger)[/] [{elapsed}]"
        )
        return

    ratio = result.ratio or 0
    color = _ratio_color(ratio)
    console.print(
        f"  [bold]\\[{idx}/{total}][/] {name} — "
        f"{_mb(result.input_size)} → {_mb(result.output_size)} "
        f"([{color}]{ratio}%[/]) [{elapsed}]"
    )


def print_dry_run(files: list[tuple[Path, Path, int, float | None]]) -> None:
    """Print what would be encoded."""
    console.print("[yellow]── DRY RUN ──[/]")
    for input_path, _, size, _ in files:
        console.print(f"  {input_path.name} ({_mb(size)})")


def print_summary(
    results: list[EncodeResult], elapsed_secs: float, config: EncoderConfig
) -> None:
    """Print per-folder stats and grand total."""
    minutes = int(elapsed_secs // 60)
    secs = int(elapsed_secs % 60)

    console.print()
    console.rule(f"[bold]COMPLETE in {minutes}m {secs}s[/bold]", style="bold")
    console.print()

    folder_stats = compute_stats(results)
    for s in folder_stats:
        console.print(
            f"  [cyan]{s.folder_name}:[/] {_mb(s.total_input)} → {_mb(s.total_output)} "
            f"({s.ratio}%) — saved {_mb(s.saved_bytes)} — {s.file_count} files"
        )

    # Grand total
    total_in = sum(s.total_input for s in folder_stats)
    total_out = sum(s.total_output for s in folder_stats)
    total_files = sum(s.file_count for s in folder_stats)
    total_saved = total_in - total_out
    grand_ratio = round(total_out * 100 / total_in) if total_in > 0 else 0

    errors = sum(1 for r in results if not r.success)
    skipped = sum(1 for r in results if r.skipped_bigger)

    console.print()
    console.rule("[bold]GRAND TOTAL[/bold]")
    console.print(f"  Files:      {total_files}")
    if errors:
        console.print(f"  [red]Errors:     {errors}[/]")
    if skipped:
        console.print(f"  [yellow]Skipped:    {skipped} (output >= original)[/]")
    console.print(f"  Original:   {_mb(total_in)} ({_gb(total_in)})")
    console.print(f"  Compressed: {_mb(total_out)} ({_gb(total_out)})")
    console.print(f"  Ratio:      {grand_ratio}%")
    console.print(f"  [green]Saved:      {_mb(total_saved)} ({_gb(total_saved)})[/]")
    console.print()
    console.print(f"  Codec: {config.codec} | Preset: {config.preset} | CQ: {config.quality}")
    console.print(f"  Parallel: {config.parallel} NVENC chips")
    console.print()
