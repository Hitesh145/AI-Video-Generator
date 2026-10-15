import os
import struct

import pytest

from animation.timing import probe_duration
from media_helpers import make_test_clip
from rendering.faststart import ensure_faststart, is_faststart
from rendering.video_renderer import mux_video


def box(kind: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def big_box(kind: bytes, payload: bytes = b"") -> bytes:
    # 64-bit "largesize" form: size field is 1, real size follows the type
    return struct.pack(">I4sQ", 1, kind, 16 + len(payload)) + payload


def write(tmp_path, *boxes):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"".join(boxes))
    return path


def test_moov_before_mdat_is_faststart(tmp_path):
    assert is_faststart(write(tmp_path, box(b"ftyp", b"isom"), box(b"free"), box(b"moov", b"m"), box(b"mdat", b"d")))


def test_mdat_before_moov_is_not_faststart(tmp_path):
    assert not is_faststart(write(tmp_path, box(b"ftyp", b"isom"), box(b"free"), box(b"mdat", b"d"), box(b"moov", b"m")))


def test_large_boxes_are_skipped_correctly(tmp_path):
    assert is_faststart(write(tmp_path, box(b"ftyp"), big_box(b"free", b"x" * 20), box(b"moov"), big_box(b"mdat", b"d")))
    assert not is_faststart(write(tmp_path, box(b"ftyp"), big_box(b"mdat", b"d" * 20), box(b"moov")))


def test_file_without_media_boxes_or_with_garbage_counts_as_fast(tmp_path):
    assert is_faststart(write(tmp_path, box(b"ftyp")))
    assert is_faststart(write(tmp_path, b"abc"))


def test_ensure_faststart_leaves_a_fast_file_alone(tmp_path):
    path = write(tmp_path, box(b"ftyp"), box(b"moov"), box(b"mdat", b"d"))
    before = path.read_bytes()

    assert ensure_faststart(path) is True
    assert path.read_bytes() == before


def test_ensure_faststart_reports_failure_without_touching_a_broken_file(tmp_path):
    path = write(tmp_path, box(b"ftyp"), box(b"mdat", b"not really video"), box(b"moov"))
    before = path.read_bytes()

    assert ensure_faststart(path) is False
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["v.mp4"]       # no temp file left behind


@pytest.mark.slow
def test_ensure_faststart_moves_the_index_to_the_front_and_keeps_duration_and_mtime(tmp_path):
    clip = make_test_clip(tmp_path / "clip.mp4", 1.0)
    os.utime(clip, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    assert not is_faststart(clip)

    assert ensure_faststart(clip) is True

    assert is_faststart(clip)
    assert probe_duration(clip) == pytest.approx(1.0, abs=0.1)
    assert clip.stat().st_mtime_ns == 1_000_000_000_000_000_000


@pytest.mark.slow
def test_mux_video_writes_the_index_first(tmp_path):
    clip = make_test_clip(tmp_path / "clip.mp4", 1.0)

    out = mux_video(clip, tmp_path / "out.mp4")

    assert is_faststart(out)
