from pathlib import Path
from typing import Callable

from rendering.faststart import ensure_faststart


def list_videos(
    output_root: Path,
    fix_video: Callable[[Path], bool] = ensure_faststart,
) -> list[dict[str, str | int]]:
    videos: list[dict[str, str | int]] = []
    for video_path in Path(output_root).rglob("lesson_demo.mp4"):
        if not video_path.is_file():
            continue

        fix_video(video_path)                 # old runs were written without +faststart
        stat = video_path.stat()
        relative_path = video_path.relative_to(output_root).as_posix()
        parent_name = video_path.parent.name.replace("-", " ").replace("_", " ")
        title = parent_name.title() if parent_name else "Lesson Demo"
        videos.append(
            {
                "id": relative_path,
                "title": title,
                "filename": video_path.name,
                "url": f"/media/{relative_path}",
                "created_at": stat.st_mtime_ns,
                "size_bytes": stat.st_size,
            }
        )

    return sorted(videos, key=lambda video: int(video["created_at"]), reverse=True)
