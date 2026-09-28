import pytest

from animation.schemas import RenderSection
from animation.slideshow import SlideshowRenderer
from animation.timing import probe_duration


@pytest.mark.slow
def test_slideshow_renders_clip_of_requested_length(tmp_path):
    section = RenderSection(index=0, title="Introduction", narration="Searching is everywhere.")

    out = SlideshowRenderer().render(section, 2.5, tmp_path / "work", tmp_path / "out.mp4")

    assert probe_duration(out) == pytest.approx(2.5, abs=0.2)
