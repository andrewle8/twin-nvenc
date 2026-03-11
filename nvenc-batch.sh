#!/bin/bash
# nvenc-batch — Dual NVENC AV1/HEVC batch video compressor
# Leverages multiple NVENC chips (RTX 4090 has 2) for parallel encoding
# https://github.com/andrewle/nvenc-batch

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────
CODEC="av1_nvenc"
PRESET="p4"
QP=32
AUDIO_BITRATE="128k"
PARALLEL=2
OUTPUT_DIR="compressed"
DRY_RUN=false
FFMPEG=""

# ── Colors ────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ── Usage ─────────────────────────────────────────────────
usage() {
  cat <<EOF
${BOLD}nvenc-batch${NC} — Dual NVENC batch video compressor

${BOLD}USAGE:${NC}
  nvenc-batch [OPTIONS] <input-dir> [input-dir2] ...

${BOLD}OPTIONS:${NC}
  -c, --codec <codec>       Encoder: av1_nvenc (default), hevc_nvenc, h264_nvenc
  -p, --preset <preset>     NVENC preset: p1 (fastest) to p7 (slowest/best) [default: p4]
  -q, --quality <qp>        Constant QP value: 0-51, higher = smaller/worse [default: 32]
  -a, --audio <bitrate>     Audio bitrate [default: 128k]
  -j, --parallel <n>        Parallel encodes (match your NVENC chip count) [default: 2]
  -o, --output <dirname>    Output subdirectory name [default: compressed]
  -f, --ffmpeg <path>       Path to ffmpeg binary [auto-detected]
      --dry-run             Show what would be encoded without doing it
  -h, --help                Show this help

${BOLD}EXAMPLES:${NC}
  nvenc-batch "F:/OBS Captures/My Videos"
  nvenc-batch -c hevc_nvenc -p p7 -q 28 /path/to/videos
  nvenc-batch -j 1 /path/to/videos                          # Single NVENC chip
  nvenc-batch "F:/folder1" "F:/folder2" "F:/folder3"         # Multiple folders

${BOLD}PRESETS:${NC}
  p1  Fastest, largest files
  p4  Good balance of speed and compression (recommended)
  p7  Slowest, smallest files (best for overnight batches)

${BOLD}QUALITY (QP):${NC}
  20-24  High quality, moderate compression
  28-32  Balanced (good for screen recordings)
  34-38  Aggressive compression (good for archival)

${BOLD}NOTES:${NC}
  - Skips files that already exist in the output directory
  - Safe to interrupt and resume — completed files are kept
  - RTX 4090 has 2 NVENC chips, most other GPUs have 1
  - AV1 encoding requires RTX 40-series or newer
EOF
  exit 0
}

# ── Find ffmpeg ───────────────────────────────────────────
find_ffmpeg() {
  if [ -n "$FFMPEG" ]; then
    if [ -f "$FFMPEG" ]; then return 0; fi
    echo -e "${RED}ERROR: ffmpeg not found at: $FFMPEG${NC}" >&2
    exit 1
  fi

  # Check PATH first
  if command -v ffmpeg &>/dev/null; then
    FFMPEG="ffmpeg"
    return 0
  fi

  # Common Windows locations
  local locations=(
    "/c/Program Files/ShareX/ffmpeg.exe"
    "/c/Program Files/ffmpeg/bin/ffmpeg.exe"
    "/c/ffmpeg/bin/ffmpeg.exe"
    "/c/tools/ffmpeg/bin/ffmpeg.exe"
    "/c/ProgramData/chocolatey/bin/ffmpeg.exe"
    "/c/Users/$USER/scoop/shims/ffmpeg.exe"
  )

  for loc in "${locations[@]}"; do
    if [ -f "$loc" ]; then
      FFMPEG="$loc"
      return 0
    fi
  done

  echo -e "${RED}ERROR: ffmpeg not found. Install it or use --ffmpeg <path>${NC}" >&2
  exit 1
}

# ── Detect NVENC chips ────────────────────────────────────
detect_nvenc_count() {
  # Try nvidia-smi to detect encoder count
  if command -v nvidia-smi &>/dev/null; then
    local gpu_name
    gpu_name=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    case "$gpu_name" in
      *4090*|*A100*|*L40*) echo 2 ;;
      *) echo 1 ;;
    esac
  else
    echo "$PARALLEL"
  fi
}

# ── Parse args ────────────────────────────────────────────
INPUT_DIRS=()

while [[ $# -gt 0 ]]; do
  case $1 in
    -c|--codec) CODEC="$2"; shift 2 ;;
    -p|--preset) PRESET="$2"; shift 2 ;;
    -q|--quality) QP="$2"; shift 2 ;;
    -a|--audio) AUDIO_BITRATE="$2"; shift 2 ;;
    -j|--parallel) PARALLEL="$2"; shift 2 ;;
    -o|--output) OUTPUT_DIR="$2"; shift 2 ;;
    -f|--ffmpeg) FFMPEG="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage ;;
    -*) echo -e "${RED}Unknown option: $1${NC}" >&2; exit 1 ;;
    *) INPUT_DIRS+=("$1"); shift ;;
  esac
done

if [ ${#INPUT_DIRS[@]} -eq 0 ]; then
  echo -e "${RED}ERROR: No input directories specified${NC}" >&2
  echo "Usage: nvenc-batch [OPTIONS] <input-dir> [input-dir2] ..."
  exit 1
fi

# ── Setup ─────────────────────────────────────────────────
find_ffmpeg

echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║         nvenc-batch — Video Compressor        ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}Codec:${NC}    $CODEC"
echo -e "  ${CYAN}Preset:${NC}   $PRESET"
echo -e "  ${CYAN}Quality:${NC}  CQ $QP"
echo -e "  ${CYAN}Audio:${NC}    $AUDIO_BITRATE"
echo -e "  ${CYAN}Parallel:${NC} $PARALLEL encodes"
echo -e "  ${CYAN}ffmpeg:${NC}   $FFMPEG"
echo ""

# ── Build file list ───────────────────────────────────────
filelist=()

for dir in "${INPUT_DIRS[@]}"; do
  if [ ! -d "$dir" ]; then
    echo -e "${YELLOW}WARN: Directory not found, skipping: $dir${NC}"
    continue
  fi

  mkdir -p "$dir/$OUTPUT_DIR"

  for file in "$dir"/*.mp4 "$dir"/*.mkv "$dir"/*.avi "$dir"/*.mov "$dir"/*.wmv "$dir"/*.webm "$dir"/*.flv; do
    [ -f "$file" ] || continue
    base=$(basename "$file")
    outname="${base%.*}.mp4"
    out="$dir/$OUTPUT_DIR/$outname"

    if [ -f "$out" ]; then
      continue
    fi
    filelist+=("$file|$out")
  done
done

total=${#filelist[@]}

if [ "$total" -eq 0 ]; then
  echo -e "${GREEN}Nothing to do — all files already compressed.${NC}"
  exit 0
fi

echo -e "${BOLD}Files to encode: $total${NC}"
echo ""

if [ "$DRY_RUN" = true ]; then
  echo -e "${YELLOW}── DRY RUN ──${NC}"
  for entry in "${filelist[@]}"; do
    IFS='|' read -r input output <<< "$entry"
    orig_size=$(stat -c%s "$input" 2>/dev/null || stat -f%z "$input" 2>/dev/null)
    echo "  $(basename "$input") ($((orig_size/1048576))MB)"
  done
  exit 0
fi

# ── Encode function ───────────────────────────────────────
encode_file() {
  local input="$1"
  local output="$2"
  local idx="$3"
  local total="$4"
  local base
  base=$(basename "$input")
  local start_time
  start_time=$(date +%s)

  "$FFMPEG" -hide_banner -hwaccel cuda -i "$input" \
    -c:v "$CODEC" -preset "$PRESET" -rc constqp -qp "$QP" \
    -c:a aac -b:a "$AUDIO_BITRATE" \
    "$output" -y 2>/dev/null

  local status=$?
  local end_time
  end_time=$(date +%s)
  local elapsed=$((end_time - start_time))

  if [ $status -eq 0 ]; then
    local orig_size new_size pct orig_mb new_mb
    orig_size=$(stat -c%s "$input" 2>/dev/null || stat -f%z "$input" 2>/dev/null)
    new_size=$(stat -c%s "$output" 2>/dev/null || stat -f%z "$output" 2>/dev/null)
    if [ -n "$orig_size" ] && [ "$orig_size" -gt 0 ]; then
      pct=$((new_size * 100 / orig_size))
      orig_mb=$((orig_size / 1048576))
      new_mb=$((new_size / 1048576))

      local color="$GREEN"
      if [ "$pct" -ge 100 ]; then color="$RED"; fi
      if [ "$pct" -ge 80 ]; then color="$YELLOW"; fi

      echo -e "  ${BOLD}[$idx/$total]${NC} $base — ${orig_mb}MB → ${new_mb}MB (${color}${pct}%${NC}) [${elapsed}s]"
    fi
  else
    echo -e "  ${RED}[$idx/$total] ERROR: $base${NC}"
    rm -f "$output" 2>/dev/null
  fi
}

# ── Main encode loop ─────────────────────────────────────
batch_start=$(date +%s)

i=0
while [ $i -lt $total ]; do
  pids=()

  # Launch up to $PARALLEL encodes
  for ((j=0; j<PARALLEL && (i+j)<total; j++)); do
    idx=$((i + j + 1))
    IFS='|' read -r input output <<< "${filelist[$((i + j))]}"
    encode_file "$input" "$output" "$idx" "$total" &
    pids+=($!)
  done

  # Wait for all in this batch
  for pid in "${pids[@]}"; do
    wait "$pid"
  done

  i=$((i + PARALLEL))
done

batch_end=$(date +%s)
batch_elapsed=$((batch_end - batch_start))
batch_min=$((batch_elapsed / 60))
batch_sec=$((batch_elapsed % 60))

# ── Final Report ──────────────────────────────────────────
echo ""
echo -e "${BOLD}══════════════════════════════════════════════${NC}"
echo -e "${BOLD}  COMPLETE in ${batch_min}m ${batch_sec}s${NC}"
echo -e "${BOLD}══════════════════════════════════════════════${NC}"
echo ""

for dir in "${INPUT_DIRS[@]}"; do
  [ -d "$dir/$OUTPUT_DIR" ] || continue
  dirname=$(basename "$dir")
  dir_orig=0; dir_comp=0; fcount=0

  for f in "$dir/$OUTPUT_DIR/"*.mp4; do
    [ -f "$f" ] || continue
    base=$(basename "$f")
    outname="${base%.*}"
    for ext in mp4 mkv avi mov wmv webm flv; do
      if [ -f "$dir/${outname}.${ext}" ]; then
        dir_orig=$((dir_orig + $(stat -c%s "$dir/${outname}.${ext}")))
        dir_comp=$((dir_comp + $(stat -c%s "$f")))
        fcount=$((fcount + 1))
        break
      fi
    done
  done

  if [ $dir_orig -gt 0 ]; then
    pct=$((dir_comp * 100 / dir_orig))
    saved=$(( (dir_orig - dir_comp) / 1048576 ))
    echo -e "  ${CYAN}$dirname:${NC} $((dir_orig/1048576))MB → $((dir_comp/1048576))MB (${pct}%) — saved ${saved}MB — $fcount files"
  fi
done

echo ""
echo -e "${BOLD}── GRAND TOTAL ──${NC}"
grand_orig=0; grand_comp=0; grand_count=0
for dir in "${INPUT_DIRS[@]}"; do
  [ -d "$dir/$OUTPUT_DIR" ] || continue
  for f in "$dir/$OUTPUT_DIR/"*.mp4; do
    [ -f "$f" ] || continue
    base=$(basename "$f")
    outname="${base%.*}"
    for ext in mp4 mkv avi mov wmv webm flv; do
      if [ -f "$dir/${outname}.${ext}" ]; then
        grand_orig=$((grand_orig + $(stat -c%s "$dir/${outname}.${ext}")))
        grand_comp=$((grand_comp + $(stat -c%s "$f")))
        grand_count=$((grand_count + 1))
        break
      fi
    done
  done
done

if [ $grand_orig -gt 0 ]; then
  grand_pct=$((grand_comp * 100 / grand_orig))
  grand_saved=$(( (grand_orig - grand_comp) / 1048576 ))
  echo -e "  Files:      $grand_count"
  echo -e "  Original:   $((grand_orig/1048576))MB ($((grand_orig/1073741824))GB)"
  echo -e "  Compressed: $((grand_comp/1048576))MB ($((grand_comp/1073741824))GB)"
  echo -e "  Ratio:      ${grand_pct}%"
  echo -e "  ${GREEN}Saved:      ${grand_saved}MB ($((grand_saved/1024))GB)${NC}"
fi

echo ""
echo -e "  Codec: $CODEC | Preset: $PRESET | QP: $QP"
echo -e "  Parallel: $PARALLEL NVENC chips"
