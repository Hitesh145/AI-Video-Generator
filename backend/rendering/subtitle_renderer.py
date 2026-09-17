from pathlib import Path
import re

from pydantic import BaseModel, Field

from services.text_normalizer import normalize_text


class SubtitleCue(BaseModel):
    index: int = Field(ge=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1)


def format_srt_timestamp(seconds: float) -> str:
    total_milliseconds = int(round(seconds * 1000))
    hours = total_milliseconds // 3_600_000
    minutes = (total_milliseconds % 3_600_000) // 60_000
    secs = (total_milliseconds % 60_000) // 1000
    millis = total_milliseconds % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_subtitle_cues(
    narrations: list[str],
    durations: list[float],
    max_chars: int = 72,
) -> list[SubtitleCue]:
    if len(narrations) != len(durations):
        raise ValueError("Narration count must match duration count.")
    if max_chars <= 0:
        raise ValueError("Subtitle max_chars must be greater than 0.")

    cues: list[SubtitleCue] = []
    cursor = 0.0

    for index, (narration, duration) in enumerate(
        zip(narrations, durations),
        start=1,
    ):
        if duration <= 0:
            raise ValueError("Subtitle durations must be greater than 0.")

        text = normalize_text(narration)
        if not text:
            cursor += duration
            continue

        chunks = _split_subtitle_text(text, max_chars)
        word_counts = [len(chunk.split()) for chunk in chunks]
        total_words = sum(word_counts)
        chunk_cursor = cursor

        for chunk_index, (chunk, word_count) in enumerate(
            zip(chunks, word_counts)
        ):
            if chunk_index == len(chunks) - 1:
                chunk_duration = cursor + duration - chunk_cursor
            else:
                chunk_duration = duration * word_count / total_words

            cues.append(
                SubtitleCue(
                    index=len(cues) + 1,
                    start_seconds=chunk_cursor,
                    end_seconds=chunk_cursor + chunk_duration,
                    text=chunk,
                )
            )
            chunk_cursor += chunk_duration

        cursor += duration

    return cues


def _split_subtitle_text(text: str, max_chars: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []

    for sentence in sentences:
        words = sentence.split()
        if not words:
            continue

        current: list[str] = []
        current_length = 0
        for word in words:
            proposed_length = current_length + len(word) + (1 if current else 0)
            if current and proposed_length > max_chars:
                chunks.append(" ".join(current))
                current = []
                current_length = 0

            current.append(word)
            current_length += len(word) + (1 if len(current) > 1 else 0)

        if current:
            chunks.append(" ".join(current))

    return chunks


def render_srt(cues: list[SubtitleCue]) -> str:
    blocks: list[str] = []

    for cue in cues:
        blocks.append(str(cue.index))
        blocks.append(
            f"{format_srt_timestamp(cue.start_seconds)} --> "
            f"{format_srt_timestamp(cue.end_seconds)}"
        )
        blocks.append(cue.text)
        blocks.append("")

    return "\n".join(blocks).strip() + "\n"


def write_srt_file(
    narrations: list[str],
    durations: list[float],
    output_path: Path,
) -> Path:
    cues = build_subtitle_cues(narrations, durations)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_srt(cues), encoding="utf-8")
    return output_path
