import re
import unicodedata


SMART_QUOTE_MAP = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u2032": "'",
    "\u2033": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\u00a0": " ",
}


def normalize_unicode(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    for source, target in SMART_QUOTE_MAP.items():
        normalized = normalized.replace(source, target)
    return normalized


def strip_markdown(text: str) -> str:
    cleaned = text
    cleaned = re.sub(r"```.*?```", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"_([^_]+)_", r"\1", cleaned)
    cleaned = re.sub(r"^#+\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    return cleaned


def normalize_text(text: str | None, fallback: str = "") -> str:
    if text is None:
        return fallback

    cleaned = normalize_unicode(str(text))
    cleaned = strip_markdown(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or fallback


def estimate_speech_duration_seconds(text: str, words_per_minute: int = 150) -> float:
    words = len(normalize_text(text).split())
    if words == 0:
        return 2.0

    seconds = (words / words_per_minute) * 60.0
    return max(2.0, round(seconds + 0.5, 2))
