"""twin-nvenc — Dual NVENC batch video compressor."""

import sys

# Ensure UTF-8 output on Windows (Rich's legacy renderer chokes on cp1252)
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

__version__ = "0.1.0"
