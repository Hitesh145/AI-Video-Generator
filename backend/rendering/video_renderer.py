from pathlib import Path
import subprocess


def render_video_from_frames(
    frame_paths: list[Path],
    output_path: Path,
    durations: list[float] | None = None,
    fps: int = 30,
    width: int = 854,
    height: int = 480,
    audio_path: Path | None = None,
    subtitle_path: Path | None = None,
) -> Path:
    """
    Convert specific PNG frames into an MP4, preserving per-frame durations.
    """
    if not frame_paths:
        raise ValueError("At least one frame is required to render a video.")

    if durations is None:
        durations = [3.0 for _ in frame_paths]

    if len(durations) != len(frame_paths):
        raise ValueError("Frame durations must match the number of frames.")

    for duration in durations:
        if duration <= 0:
            raise ValueError("Frame durations must be greater than 0.")

    if fps <= 0:
        raise ValueError("fps must be greater than 0.")

    if width <= 0 or height <= 0:
        raise ValueError("Video width and height must be greater than 0.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_path = output_path.parent / "frames.ffconcat"

    lines = ["ffconcat version 1.0"]
    for frame_path, duration in zip(frame_paths, durations):
        escaped_path = str(frame_path.resolve()).replace("\\", "/").replace("'", "'\\''")
        lines.append(f"file '{escaped_path}'")
        lines.append(f"duration {duration:g}")

    last_frame = str(frame_paths[-1].resolve()).replace("\\", "/").replace("'", "'\\''")
    lines.append(f"file '{last_frame}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    video_only_path = output_path
    if audio_path is not None or subtitle_path is not None:
        video_only_path = output_path.parent / f"{output_path.stem}_video_only.mp4"

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-vf",
        f"scale={width}:{height}:flags=lanczos,fps={fps}",
        str(video_only_path),
    ]

    subprocess.run(
        command,
        check=True,
    )

    if audio_path is None and subtitle_path is None:
        return video_only_path

    if audio_path is not None and not audio_path.exists():
        raise ValueError(f"Audio file not found: {audio_path}")
    if subtitle_path is not None and not subtitle_path.exists():
        raise ValueError(f"Subtitle file not found: {subtitle_path}")

    mux_command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_only_path),
    ]
    if audio_path is not None:
        mux_command.extend(["-i", str(audio_path)])
    if subtitle_path is not None:
        mux_command.extend(["-i", str(subtitle_path)])

    mux_command.extend(["-map", "0:v:0"])
    if audio_path is not None:
        mux_command.extend(["-map", "1:a:0", "-c:a", "aac", "-b:a", "128k"])
    if subtitle_path is not None:
        subtitle_input_index = 2 if audio_path is not None else 1
        mux_command.extend(
            [
                "-map",
                f"{subtitle_input_index}:s:0",
                "-c:s",
                "mov_text",
                "-metadata:s:s:0",
                "language=eng",
            ]
        )
    mux_command.extend(["-c:v", "copy", "-shortest", str(output_path)])

    subprocess.run(
        mux_command,
        check=True,
    )

    return output_path


def render_video(
    frames_dir: Path,
    output_path: Path,
    seconds_per_frame: float = 3.0,
    fps: int = 30,
    width: int = 854,
    height: int = 480,
) -> Path:
    """
    Convert sequential PNG frames into an MP4 video using FFmpeg.
    """
    if seconds_per_frame <= 0:
        raise ValueError("seconds_per_frame must be greater than 0.")

    if fps <= 0:
        raise ValueError("fps must be greater than 0.")

    if width <= 0 or height <= 0:
        raise ValueError("Video width and height must be greater than 0.")

    frame_pattern = frames_dir / "frame_%02d.png"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-y",
        "-framerate",
        f"1/{seconds_per_frame:g}",
        "-i",
        str(frame_pattern),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-vf",
        f"scale={width}:{height}:flags=lanczos,fps={fps}",
        str(output_path),
    ]

    subprocess.run(
        command,
        check=True,
    )

    return output_path


def main() -> None:
    frames_dir = Path("output/frames")
    output_path = Path("output/demo.mp4")

    video_path = render_video(
        frames_dir=frames_dir,
        output_path=output_path,
    )

    print(f"Video created: {video_path}")


if __name__ == "__main__":
    main()
