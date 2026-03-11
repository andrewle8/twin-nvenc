"""Textual TUI for real-time encoding dashboard."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Footer, Header, Label, ProgressBar, Static

from twin_nvenc.encoder import EncodeResult, EncoderConfig, encode_batch
from twin_nvenc.scanner import FileInfo


# ── Messages ─────────────────────────────────────────────


class FileStarted(Message):
    def __init__(self, idx: int, total: int, path: Path) -> None:
        super().__init__()
        self.idx = idx
        self.total = total
        self.path = path


class ProgressUpdate(Message):
    def __init__(self, idx: int, progress: dict) -> None:
        super().__init__()
        self.idx = idx
        self.progress = progress


class FileDone(Message):
    def __init__(self, idx: int, total: int, result: EncodeResult) -> None:
        super().__init__()
        self.idx = idx
        self.total = total
        self.result = result


class BatchDone(Message):
    def __init__(self, results: list[EncodeResult], elapsed: float) -> None:
        super().__init__()
        self.results = results
        self.elapsed = elapsed


# ── Widgets ──────────────────────────────────────────────


class EncoderSlot(Static):
    """Shows one NVENC chip's current encode status."""

    file_name: reactive[str] = reactive("")
    percent: reactive[float] = reactive(0.0)
    speed: reactive[str] = reactive("")
    eta: reactive[str] = reactive("")
    slot_id: int = 0
    active: reactive[bool] = reactive(False)

    def __init__(self, slot_id: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self.slot_id = slot_id

    def render(self) -> Text:
        if not self.active:
            return Text(f"  NVENC #{self.slot_id}: idle", style="dim")

        bar_width = 30
        filled = int(self.percent / 100 * bar_width)
        empty = bar_width - filled
        bar = "█" * filled + "░" * empty
        pct = f"{self.percent:5.1f}%"

        parts = f"  NVENC #{self.slot_id}: {self.file_name}\n"
        parts += f"  [{bar}] {pct}"
        if self.speed:
            parts += f"  {self.speed}"
        if self.eta:
            parts += f"  ETA {self.eta}"

        return Text(parts)


class CompletedList(Static):
    """Shows completed encode results."""

    results: reactive[list] = reactive(list, always_update=True)

    def render(self) -> Text:
        text = Text()
        if not self.results:
            text.append("  No files completed yet", style="dim")
            return text

        # Show last 8 results
        shown = self.results[-8:]
        for r in shown:
            name = r.input_path.name
            if len(name) > 35:
                name = name[:32] + "..."

            if not r.success:
                text.append(f"  x {name} — ERROR\n", style="red")
            elif r.skipped_bigger:
                ratio = r.ratio or 100
                text.append(
                    f"  ~ {name} — {_mb(r.input_size)} -> {_mb(r.output_size)} "
                    f"({ratio}%) SKIPPED\n",
                    style="yellow",
                )
            else:
                ratio = r.ratio or 0
                style = "green" if ratio < 80 else "yellow" if ratio < 100 else "red"
                text.append(
                    f"  + {name} — {_mb(r.input_size)} -> {_mb(r.output_size)} "
                    f"({ratio}%) [{r.elapsed_secs:.0f}s]\n",
                    style=style,
                )
        return text


class StatsBar(Static):
    """Running totals at the bottom."""

    completed: reactive[int] = reactive(0)
    total: reactive[int] = reactive(0)
    errors: reactive[int] = reactive(0)
    saved_bytes: reactive[int] = reactive(0)
    elapsed: reactive[float] = reactive(0.0)
    done: reactive[bool] = reactive(False)

    def render(self) -> Text:
        mins = int(self.elapsed // 60)
        secs = int(self.elapsed % 60)
        saved = _mb(self.saved_bytes)

        status = "DONE" if self.done else "encoding"
        parts = f"  {self.completed}/{self.total} files | {saved} saved | {mins}m {secs}s | {status}"
        if self.errors:
            parts += f" | {self.errors} errors"

        style = "bold green" if self.done else "bold"
        return Text(parts, style=style)


# ── Helpers ──────────────────────────────────────────────


def _mb(n: int) -> str:
    return f"{n // 1_048_576}MB"


def _format_eta(secs: float | None) -> str:
    if secs is None or secs < 0:
        return ""
    m = int(secs // 60)
    s = int(secs % 60)
    return f"{m}:{s:02d}"


# ── App ──────────────────────────────────────────────────


class TwinNvencApp(App):
    """TUI dashboard for twin-nvenc batch encoding."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #banner {
        height: 3;
        content-align: center middle;
        text-style: bold;
        background: $surface;
        border-bottom: solid $primary;
    }

    #encoder-panel {
        height: auto;
        max-height: 10;
        border-bottom: solid $surface-lighten-2;
        padding: 0 1;
    }

    #queue-label {
        height: 1;
        padding: 0 1;
        text-style: bold;
        background: $surface;
    }

    #completed-label {
        height: 1;
        padding: 0 1;
        text-style: bold;
        background: $surface;
    }

    #completed-panel {
        height: 1fr;
        min-height: 5;
        padding: 0 1;
    }

    #stats-bar {
        height: 1;
        dock: bottom;
        background: $primary;
        color: $text;
    }

    EncoderSlot {
        height: 3;
        padding: 0;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        file_infos: list[FileInfo],
        config: EncoderConfig,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.file_infos = file_infos
        self.config = config
        self._results: list[EncodeResult] = []
        self._active_slots: dict[int, int] = {}  # idx -> slot_id
        self._start_time = 0.0
        self._timer_handle: asyncio.TimerHandle | None = None

    def compose(self) -> ComposeResult:
        codec = self.config.codec
        cq = self.config.quality
        preset = self.config.preset
        parallel = self.config.parallel

        yield Static(
            f"  twin-nvenc | {codec} | CQ {cq} | {preset} | {parallel} chips",
            id="banner",
        )

        with Vertical(id="encoder-panel"):
            for i in range(1, self.config.parallel + 1):
                yield EncoderSlot(slot_id=i, id=f"slot-{i}")

        yield Static(
            f"  Queue: {len(self.file_infos)} files",
            id="queue-label",
        )
        yield Static("  Completed:", id="completed-label")
        yield CompletedList(id="completed-panel")
        yield StatsBar(id="stats-bar")

    def on_mount(self) -> None:
        stats = self.query_one("#stats-bar", StatsBar)
        stats.total = len(self.file_infos)
        self._start_time = time.monotonic()
        self._start_timer()
        # Launch encoding as an async task on the same event loop
        asyncio.get_event_loop().create_task(self._run_encode())

    def _start_timer(self) -> None:
        """Update elapsed time every second."""

        def _tick() -> None:
            stats = self.query_one("#stats-bar", StatsBar)
            stats.elapsed = time.monotonic() - self._start_time
            self._timer_handle = asyncio.get_event_loop().call_later(1.0, _tick)

        _tick()

    async def _run_encode(self) -> None:
        app = self
        file_tuples = [
            (fi.input_path, fi.output_path, fi.size_bytes, fi.duration_secs)
            for fi in self.file_infos
        ]

        def on_start(idx: int, total: int, path: Path) -> None:
            app.post_message(FileStarted(idx, total, path))

        def on_done(idx: int, total: int, result: EncodeResult) -> None:
            app.post_message(FileDone(idx, total, result))

        def on_progress(idx: int, progress: dict) -> None:
            app.post_message(ProgressUpdate(idx, progress))

        start = time.monotonic()
        results = await encode_batch(
            file_tuples,
            self.config,
            on_file_start=on_start,
            on_file_done=on_done,
            on_progress=on_progress,
        )
        elapsed = time.monotonic() - start
        app.post_message(BatchDone(results, elapsed))

    def on_file_started(self, message: FileStarted) -> None:
        # Find a free slot
        used_slots = set(self._active_slots.values())
        for i in range(1, self.config.parallel + 1):
            if i not in used_slots:
                slot = self.query_one(f"#slot-{i}", EncoderSlot)
                slot.file_name = message.path.name
                slot.percent = 0.0
                slot.speed = ""
                slot.eta = ""
                slot.active = True
                self._active_slots[message.idx] = i
                break

        # Update queue count
        remaining = message.total - message.idx
        queue_label = self.query_one("#queue-label", Static)
        queue_label.update(f"  Queue: {remaining} remaining")

    def on_progress_update(self, message: ProgressUpdate) -> None:
        slot_id = self._active_slots.get(message.idx)
        if slot_id is None:
            return

        slot = self.query_one(f"#slot-{slot_id}", EncoderSlot)
        p = message.progress
        if p.get("percent") is not None:
            slot.percent = min(p["percent"], 100.0)
        if p.get("speed"):
            slot.speed = p["speed"]
        if p.get("eta_secs") is not None:
            slot.eta = _format_eta(p["eta_secs"])

    def on_file_done(self, message: FileDone) -> None:
        # Clear the slot
        slot_id = self._active_slots.pop(message.idx, None)
        if slot_id:
            slot = self.query_one(f"#slot-{slot_id}", EncoderSlot)
            slot.active = False

        # Update results
        self._results.append(message.result)
        completed_list = self.query_one("#completed-panel", CompletedList)
        completed_list.results = list(self._results)
        completed_list.mutate_reactive(CompletedList.results)

        # Update stats
        stats = self.query_one("#stats-bar", StatsBar)
        stats.completed = len(self._results)

        r = message.result
        if not r.success:
            stats.errors += 1
        elif not r.skipped_bigger and r.output_size > 0:
            stats.saved_bytes += r.input_size - r.output_size

        # Update completed label
        label = self.query_one("#completed-label", Static)
        label.update(f"  Completed: {len(self._results)}/{message.total}")

    def on_batch_done(self, message: BatchDone) -> None:
        if self._timer_handle:
            self._timer_handle.cancel()

        stats = self.query_one("#stats-bar", StatsBar)
        stats.elapsed = message.elapsed
        stats.done = True

        queue_label = self.query_one("#queue-label", Static)
        queue_label.update("  Queue: done")


def run_tui(file_infos: list[FileInfo], config: EncoderConfig) -> None:
    """Launch the TUI app."""
    app = TwinNvencApp(file_infos, config)
    app.run()
