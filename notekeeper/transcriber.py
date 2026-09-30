"""Transcripción de audio con faster-whisper."""
from pathlib import Path

from notekeeper.config import WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE


def _resolve_device() -> str:
    if WHISPER_DEVICE != "auto":
        return WHISPER_DEVICE
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _resolve_compute() -> str:
    device = _resolve_device()
    if device == "cpu":
        return "int8"
    return WHISPER_COMPUTE


def load_model():
    from faster_whisper import WhisperModel

    device = _resolve_device()
    compute = _resolve_compute()

    print(f"Cargando modelo {WHISPER_MODEL} ({device}/{compute})...")
    model = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute)
    print("Modelo cargado.")
    return model


def transcribe_file(audio_path: Path, model=None) -> dict:
    """Transcribe un archivo de audio.

    Returns:
        {
            "language": "es",
            "duration": 3600.0,
            "segments": [{"start": 0.0, "end": 5.2, "text": "..."}],
            "text": "transcripción completa"
        }
    """
    if model is None:
        model = load_model()

    print(f"Transcribiendo: {audio_path.name}...")

    segments_gen, info = model.transcribe(
        str(audio_path),
        language=None,  # auto-detect
        beam_size=3,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,
            speech_pad_ms=200,
        ),
    )

    language = info.language
    duration = info.duration
    print(f"Idioma detectado: {language}")
    print(f"Duración: {duration:.1f}s")

    segments = []
    full_text_parts = []
    last_pct = -1
    for seg in segments_gen:
        segments.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
        })
        full_text_parts.append(seg.text.strip())
        if duration > 0:
            pct = int(seg.end / duration * 100)
            if pct >= last_pct + 10:
                last_pct = pct
                print(f"  Progreso: {pct}% ({seg.end:.0f}s/{duration:.0f}s)", flush=True)

    full_text = " ".join(full_text_parts)
    print(f"Segmentos: {len(segments)}")

    return {
        "language": language,
        "duration": round(duration, 2),
        "segments": segments,
        "text": full_text,
    }


def format_transcript(result: dict) -> str:
    """Formatea el resultado como texto legible con timestamps."""
    lines = []
    lines.append(f"Idioma: {result['language']}")
    lines.append(f"Duración: {result['duration']:.1f}s")
    lines.append(f"Segmentos: {len(result['segments'])}")
    lines.append("")
    lines.append("=" * 60)
    lines.append("TRANSCRIPCIÓN")
    lines.append("=" * 60)
    lines.append("")

    for seg in result["segments"]:
        start = _format_time(seg["start"])
        lines.append(f"[{start}] {seg['text']}")
        lines.append("")

    return "\n".join(lines)


def _format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
