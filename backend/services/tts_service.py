import asyncio
import subprocess
import wave
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from rendering.caption_renderer import narration_for_scene
from schemas.lesson import LessonScript
from schemas.visual import ScenePlan, VisualScene
from services.text_normalizer import estimate_speech_duration_seconds, normalize_text


class SceneAudio(BaseModel):
    scene_id: str = Field(description="Visual scene identifier.")
    narration_text: str = Field(description="Normalized narration spoken for the scene.")
    audio_path: str = Field(description="Path to the generated audio file.")
    duration_seconds: float = Field(
        gt=0,
        description="Measured or estimated duration of the scene audio.",
    )


class TTSSynthesizer(Protocol):
    def synthesize_scene_audio(
        self,
        scene: VisualScene,
        narration_text: str,
        output_path: Path,
    ) -> SceneAudio:
        ...


def _write_silent_wav(output_path: Path, duration_seconds: float) -> None:
    sample_rate = 22050
    frame_count = max(1, int(sample_rate * duration_seconds))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(output_path), "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)


def _measure_wav_duration_seconds(audio_path: Path) -> float:
    try:
        with wave.open(str(audio_path), "r") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            if rate <= 0:
                raise ValueError(f"Invalid sample rate in audio file: {audio_path}")
            return round(frames / rate, 2)
    except wave.Error:
        return _measure_audio_duration_seconds_fallback(audio_path)


def _measure_audio_duration_seconds_fallback(audio_path: Path) -> float:
    if not audio_path.exists():
        raise ValueError(f"Audio file not found: {audio_path}")

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        size = audio_path.stat().st_size
        estimate = max(1.0, round(size / 2000.0, 2))
        return estimate

    raw_duration = result.stdout.strip()
    if not raw_duration:
        size = audio_path.stat().st_size
        estimate = max(1.0, round(size / 2000.0, 2))
        return estimate

    duration = float(raw_duration)
    if duration <= 0:
        size = audio_path.stat().st_size
        estimate = max(1.0, round(size / 2000.0, 2))
        return estimate
    return round(duration, 2)


class FakeTTSService:
    """
    Deterministic TTS for tests. Writes silent WAV files with estimated duration.
    """

    def synthesize_scene_audio(
        self,
        scene: VisualScene,
        narration_text: str,
        output_path: Path,
    ) -> SceneAudio:
        normalized = normalize_text(narration_text, fallback=scene.description)
        duration = estimate_speech_duration_seconds(normalized)
        _write_silent_wav(output_path, duration)

        return SceneAudio(
            scene_id=scene.id,
            narration_text=normalized,
            audio_path=str(output_path),
            duration_seconds=_measure_wav_duration_seconds(output_path),
        )


class SilentTTSService(FakeTTSService):
    """
    Offline fallback that creates silent narration tracks sized to speech estimates.
    """


class EdgeTTSService:
    """
    Uses Microsoft Edge neural voices through edge-tts when installed.
    """

    def __init__(self, voice: str = "en-US-JennyNeural") -> None:
        self.voice = voice

    def synthesize_scene_audio(
        self,
        scene: VisualScene,
        narration_text: str,
        output_path: Path,
    ) -> SceneAudio:
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError(
                "edge-tts is not installed. Install it with: pip install edge-tts"
            ) from exc

        normalized = normalize_text(narration_text, fallback=scene.description)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        async def _run() -> None:
            communicate = edge_tts.Communicate(normalized, self.voice)
            await communicate.save(str(output_path))

        asyncio.run(_run())

        try:
            duration = _measure_audio_duration_seconds(output_path)
        except Exception:
            duration = estimate_speech_duration_seconds(normalized)

        return SceneAudio(
            scene_id=scene.id,
            narration_text=normalized,
            audio_path=str(output_path),
            duration_seconds=duration,
        )


def _measure_audio_duration_seconds(audio_path: Path) -> float:
    if audio_path.suffix.lower() == ".wav":
        try:
            return _measure_wav_duration_seconds(audio_path)
        except (OSError, ValueError):
            return _measure_audio_duration_seconds_fallback(audio_path)

    return _measure_audio_duration_seconds_fallback(audio_path)


class SceneTTSService:
    def __init__(self, synthesizer: TTSSynthesizer) -> None:
        self.synthesizer = synthesizer

    def synthesize_scene_plan(
        self,
        scene_plan: ScenePlan,
        lesson_script: LessonScript,
        output_dir: Path,
    ) -> list[SceneAudio]:
        audio_dir = output_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        scene_audio: list[SceneAudio] = []
        for index, scene in enumerate(scene_plan.scenes, start=1):
            narration = narration_for_scene(scene, lesson_script)
            audio_path = audio_dir / f"scene_{index:02d}.wav"
            scene_audio.append(
                self.synthesizer.synthesize_scene_audio(
                    scene=scene,
                    narration_text=narration,
                    output_path=audio_path,
                )
            )

        return scene_audio


def concat_scene_audio(scene_audio: list[SceneAudio], output_path: Path) -> Path:
    if not scene_audio:
        raise ValueError("At least one scene audio track is required.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_path = output_path.parent / "audio.ffconcat"

    lines = ["ffconcat version 1.0"]
    for audio in scene_audio:
        escaped_path = (
            str(Path(audio.audio_path).resolve())
            .replace("\\", "/")
            .replace("'", "'\\''")
        )
        lines.append(f"file '{escaped_path}'")

    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(output_path),
    ]
    subprocess.run(command, check=True)
    return output_path
