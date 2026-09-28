import pytest

from animation.timing import (
    concat_audio_padded,
    concat_clips,
    fit_clip,
    fit_filter,
    probe_duration,
    step_durations_for_segment,
)
from media_helpers import make_test_clip, make_tone


def test_single_step_gets_all_audio_time():
    assert step_durations_for_segment(2.5, 0) == [2.5]


def test_grouped_steps_get_fixed_time():
    assert step_durations_for_segment(3.0, 2) == [1.8, 0.6, 0.6]


def test_narrated_step_has_minimum():
    assert step_durations_for_segment(1.0, 3) == [1.0, 0.6, 0.6, 0.6]


def test_fit_filter_pads_short_clip():
    assert fit_filter(2.0, 3.0) == "tpad=stop_mode=clone:stop_duration=1.000"


def test_fit_filter_speeds_up_slightly_long_clip():
    assert fit_filter(2.2, 2.0) == "setpts=PTS*0.909091"


def test_fit_filter_caps_speedup_for_very_long_clip():
    assert fit_filter(10.0, 2.0) == "setpts=PTS/1.15"


def test_fit_filter_rejects_non_positive():
    with pytest.raises(ValueError):
        fit_filter(0, 2.0)


@pytest.mark.slow
@pytest.mark.parametrize("target", [3.0, 1.8])
def test_fit_clip_hits_target(tmp_path, target):
    clip = make_test_clip(tmp_path / "in.mp4", 2.0)
    fitted = fit_clip(clip, target, tmp_path / "out.mp4")

    assert probe_duration(fitted) == pytest.approx(target, abs=0.1)


@pytest.mark.slow
def test_fit_clip_trims_long_clip(tmp_path):
    clip = make_test_clip(tmp_path / "in.mp4", 6.0)
    fitted = fit_clip(clip, 2.0, tmp_path / "out.mp4")

    assert probe_duration(fitted) == pytest.approx(2.0, abs=0.1)


@pytest.mark.slow
def test_concat_audio_padded_uses_given_durations(tmp_path):
    first = make_tone(tmp_path / "a.wav", 1.0)
    second = make_tone(tmp_path / "b.wav", 1.0)
    out = concat_audio_padded([first, second], [1.5, 2.0], tmp_path / "out.m4a")

    assert probe_duration(out) == pytest.approx(3.5, abs=0.1)


@pytest.mark.slow
def test_concat_clips_sums_durations(tmp_path):
    a = fit_clip(make_test_clip(tmp_path / "a.mp4", 1.0), 1.0, tmp_path / "fa.mp4")
    b = fit_clip(make_test_clip(tmp_path / "b.mp4", 2.0), 2.0, tmp_path / "fb.mp4")
    out = concat_clips([a, b], tmp_path / "out.mp4")

    assert probe_duration(out) == pytest.approx(3.0, abs=0.15)


@pytest.mark.slow
def test_concat_clips_handles_apostrophe_in_path(tmp_path):
    folder = tmp_path / "o'brien"
    a = fit_clip(make_test_clip(folder / "a.mp4", 1.0), 1.0, folder / "fa.mp4")
    out = concat_clips([a, a], folder / "out.mp4")

    assert probe_duration(out) == pytest.approx(2.0, abs=0.15)
