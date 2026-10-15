import os

import pytest

from media_helpers import make_test_clip
from rendering.faststart import is_faststart
from services.video_library import list_videos


def make_video(root, name, mtime_ns, content=b"v"):
    folder = root / name
    folder.mkdir(parents=True)
    video = folder / "lesson_demo.mp4"
    video.write_bytes(content)
    os.utime(video, ns=(mtime_ns, mtime_ns))
    return video


def test_lists_only_finished_videos_newest_first(tmp_path):
    older = make_video(tmp_path, "binary-search-aaaa1111", 1_000_000_000)
    newer = make_video(tmp_path, "linear-search-bbbb2222", 2_000_000_000, b"vv")
    (newer.parent / "lesson_video_only.mp4").write_bytes(b"x")            # ignored
    (tmp_path / "_failed" / "abc").mkdir(parents=True)
    (tmp_path / "_failed" / "abc" / "llm_calls.json").write_text("{}", encoding="utf-8")

    videos = list_videos(tmp_path, fix_video=lambda path: True)

    assert [v["id"] for v in videos] == [
        "linear-search-bbbb2222/lesson_demo.mp4",
        "binary-search-aaaa1111/lesson_demo.mp4",
    ]
    first = videos[0]
    assert first["title"] == "Linear Search Bbbb2222"
    assert first["filename"] == "lesson_demo.mp4"
    assert first["url"] == "/media/linear-search-bbbb2222/lesson_demo.mp4"
    assert first["size_bytes"] == 2
    assert first["created_at"] == 2_000_000_000
    assert older.exists()


def test_every_listed_video_is_passed_to_the_fixer(tmp_path):
    a = make_video(tmp_path, "run-a", 1)
    b = make_video(tmp_path, "run-b", 2)
    seen = []

    list_videos(tmp_path, fix_video=lambda path: seen.append(path) or True)

    assert sorted(seen) == sorted([a, b])


def test_empty_output_root_lists_nothing(tmp_path):
    assert list_videos(tmp_path, fix_video=lambda path: True) == []


@pytest.mark.slow
def test_listing_makes_old_videos_fast_start_without_changing_their_order(tmp_path):
    old = tmp_path / "old-run"
    old.mkdir()
    clip = make_test_clip(old / "lesson_demo.mp4", 1.0)
    os.utime(clip, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    assert not is_faststart(clip)

    videos = list_videos(tmp_path)

    assert is_faststart(clip)
    assert videos[0]["created_at"] == 1_000_000_000_000_000_000


def test_recently_written_videos_are_left_alone(tmp_path):
    folder = tmp_path / "run"
    folder.mkdir()
    (folder / "lesson_demo.mp4").write_bytes(b"v")           # modified just now: a mux may still be writing it
    seen = []

    videos = list_videos(tmp_path, fix_video=lambda path: seen.append(path) or True)

    assert seen == []
    assert len(videos) == 1
