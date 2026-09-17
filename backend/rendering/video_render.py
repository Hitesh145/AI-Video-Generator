from pathlib import Path
import subprocess


def render_video(
    frames_dir: Path,
    output_path: Path,
    fps: int = 30,
) -> None:
    """
    Convert sequential PNG frames into an MP4 video using FFmpeg.
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-y",
        "-framerate",
        "0.5",
        "-i",
        str(frames_dir / "frame_%02d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-vf",
        f"scale=1280:720:flags=lanczos,fps={fps}",
        str(output_path),
    ]

    subprocess.run(
        command,
        check=True,
    )


def main() -> None:
    frames_dir = Path("output/binary_search_frames")
    output_path = Path("output/binary_search.mp4")

    render_video(
        frames_dir=frames_dir,
        output_path=output_path,
    )

    print(f"Video created: {output_path}")


if __name__ == "__main__":
    main()