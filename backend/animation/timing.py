import subprocess
from pathlib import Path


WIDTH = 854
HEIGHT = 480
FPS = 30
GROUPED_STEP_SECONDS = 0.6
MIN_NARRATED_STEP_SECONDS = 1.0
MAX_SPEEDUP = 1.15


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def step_durations_for_segment(audio_seconds: float, grouped_count: int) -> list[float]:
    """First step is narrated; the grouped steps that follow play quickly under it."""
    narrated = max(
        MIN_NARRATED_STEP_SECONDS,
        audio_seconds - GROUPED_STEP_SECONDS * grouped_count,
    )
    return [round(narrated, 3)] + [GROUPED_STEP_SECONDS] * grouped_count


def fit_filter(actual: float, target: float) -> str:
    if actual <= 0 or target <= 0:
        raise ValueError("Durations must be greater than 0.")
    if actual < target:
        return f"tpad=stop_mode=clone:stop_duration={target - actual:.3f}"
    if actual <= target * MAX_SPEEDUP:
        return f"setpts=PTS*{target / actual:.6f}"
    return f"setpts=PTS/{MAX_SPEEDUP}"


def fit_clip(input_path: Path, target_seconds: float, output_path: Path) -> Path:
    """Re-encode a clip to the house format with exactly target_seconds of video."""
    actual = probe_duration(input_path)
    video_filter = (
        f"{fit_filter(actual, target_seconds)},"
        f"scale={WIDTH}:{HEIGHT}:flags=lanczos,fps={FPS},format=yuv420p"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-i", str(input_path),
            "-vf", video_filter,
            "-an",
            "-c:v", "libx264",
            "-t", f"{target_seconds:.3f}",
            str(output_path),
        ],
        check=True,
    )
    return output_path


def concat_audio_padded(paths: list[Path], durations: list[float], output_path: Path) -> Path:
    """Concatenate audio files, padding or trimming each one to its given duration."""
    if not paths:
        raise ValueError("At least one audio file is required.")
    if len(paths) != len(durations):
        raise ValueError("Audio paths and durations must have the same length.")

    command = ["ffmpeg", "-y", "-v", "error"]
    for path in paths:
        command.extend(["-i", str(path)])

    filters = [
        f"[{index}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono,"
        f"apad=whole_dur={duration:.3f},atrim=0:{duration:.3f}[a{index}]"
        for index, duration in enumerate(durations)
    ]
    labels = "".join(f"[a{index}]" for index in range(len(paths)))
    filters.append(f"{labels}concat=n={len(paths)}:v=0:a=1[out]")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[out]",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path),
    ])
    subprocess.run(command, check=True)
    return output_path


def concat_clips(paths: list[Path], output_path: Path) -> Path:
    """Concatenate clips that were all normalised by fit_clip."""
    if not paths:
        raise ValueError("At least one clip is required.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    list_path = output_path.with_suffix(".ffconcat")
    lines = ["ffconcat version 1.0"]
    for path in paths:
        escaped = str(path.resolve()).replace("\\", "/").replace("'", "'\''")
        lines.append(f"file '{escaped}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0",
            "-i", str(list_path),
            "-c", "copy",
            str(output_path),
        ],
        check=True,
    )
    return output_path
