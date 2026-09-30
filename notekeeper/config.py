import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.getenv("NOTEKEEPER_DATA", "recordings"))
NOTEKEEPER_SYSTEM_DEVICE = os.getenv("NOTEKEEPER_SYSTEM_DEVICE", "BlackHole 2ch")
NOTEKEEPER_MIC_DEVICE = os.getenv("NOTEKEEPER_MIC_DEVICE", "")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "medium")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)