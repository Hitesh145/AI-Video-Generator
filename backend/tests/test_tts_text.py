from services.tts_service import FakeTTSService


def test_fake_tts_synthesizes_plain_text(tmp_path):
    audio = FakeTTSService().synthesize_text("**Binary** search halves the range.", tmp_path / "seg_001.wav")

    assert audio.scene_id == "seg_001"
    assert audio.narration_text == "Binary search halves the range."
    assert audio.duration_seconds >= 2.0
    assert (tmp_path / "seg_001.wav").exists()


def test_fake_tts_handles_empty_text(tmp_path):
    audio = FakeTTSService().synthesize_text("   ", tmp_path / "empty.wav")

    assert audio.duration_seconds >= 2.0
