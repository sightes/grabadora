"""Gestión de archivos de grabaciones y transcripciones."""
import json
from datetime import datetime
from pathlib import Path

from notekeeper.config import DATA_DIR, AUDIO_EXTENSIONS


def _format_dir_name(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d_%H-%M-%S")


def create_session(dt: datetime | None = None) -> Path:
    dt = dt or datetime.now()
    session_dir = DATA_DIR / _format_dir_name(dt)
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def get_session_dir(session_id: str) -> Path:
    return DATA_DIR / session_id


def list_sessions(tags: list[str] | None = None) -> list[Path]:
    if not DATA_DIR.exists():
        return []
    sessions = sorted(
        [d for d in DATA_DIR.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )
    if tags:
        tags = {t.lower() for t in tags}
        sessions = [s for s in sessions if tags.intersection(get_tags(s))]
    return sessions


def find_audio_files() -> list[tuple[Path, Path | None]]:
    """Devuelve [(audio_path, session_dir), ...] de todas las sesiones."""
    results = []
    for session in list_sessions():
        for f in session.iterdir():
            if f.suffix.lower() in AUDIO_EXTENSIONS:
                results.append((f, session))
    return results


def find_untranscribed() -> list[tuple[Path, Path]]:
    """Encuentra audios que aún no tienen transcript.txt."""
    results = []
    for audio_path, session in find_audio_files():
        transcript = session / "transcript.txt"
        if not transcript.exists():
            results.append((audio_path, session))
    return results


def save_transcript(session: Path, text: str, segments: list[dict]) -> None:
    (session / "transcript.txt").write_text(text, encoding="utf-8")
    (session / "segments.json").write_text(
        json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def save_metadata(session: Path, metadata: dict) -> None:
    meta_path = session / "metadata.json"
    existing = {}
    if meta_path.exists():
        existing = json.loads(meta_path.read_text(encoding="utf-8"))
    existing.update(metadata)
    meta_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def load_metadata(session: Path) -> dict:
    meta_path = session / "metadata.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {}


def get_tags(session: Path) -> set[str]:
    """Tags (contextos) asignados a una sesión, en minúsculas."""
    meta = load_metadata(session)
    return {str(t).strip().lower() for t in (meta.get("tags") or []) if str(t).strip()}


def add_tags(session: Path, tags: list[str]) -> set[str]:
    """Añade tags a una sesión y los persiste en metadata.json."""
    tags = {str(t).strip().lower() for t in tags if str(t).strip()}
    if not tags:
        return get_tags(session)
    current = get_tags(session)
    current.update(tags)
    save_metadata(session, {"tags": sorted(current)})
    return current


def get_audio_path(session: Path) -> Path | None:
    for f in session.iterdir():
        if f.suffix.lower() in AUDIO_EXTENSIONS:
            return f
    return None


def get_transcript_text(session: Path) -> str | None:
    transcript = session / "transcript.txt"
    if transcript.exists():
        return transcript.read_text(encoding="utf-8")
    return None
