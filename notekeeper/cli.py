#!/usr/bin/env python3
"""Notekeeper - CLI para grabar y transcribir reuniones."""
import argparse
import re
import sys


def extract_tags(args_list: list[str]) -> tuple[list[str], list[str]]:
    """Separa tokens `#tag` (p. ej. `#scotiabank`) del resto de los argumentos."""
    tags = []
    rest = []
    for a in args_list:
        for tok in a.split():
            if re.fullmatch(r"#[\w\-]+", tok):
                tags.append(tok[1:])
            else:
                rest.append(tok)
    return tags, rest


def cmd_rec(args):
    from notekeeper.recorder import record, list_devices

    if args.list:
        list_devices()
        return

    extra = getattr(args, "extra", None) or []
    extra_tags, _ = extract_tags(extra)
    all_tags = list(args.tags or []) + extra_tags

    print("=== Notekeeper - Grabar ===\n")
    mic = args.mic if args.mic else (True if args.add_mic else None)
    record(device=args.device, duration=args.duration, output=args.output, mic=mic, tags=all_tags or None)


def cmd_transcript(args):
    from notekeeper.transcriber import transcribe_file, format_transcript, load_model
    from notekeeper.storage import (
        find_untranscribed,
        save_transcript,
        save_metadata,
        get_audio_path,
        list_sessions,
    )

    if getattr(args, "tag", None) and not args.session:
        sessions = list_sessions(tags=[args.tag])
        untranscribed = []
        for session in sessions:
            audio = get_audio_path(session)
            if audio and not (session / "transcript.txt").exists():
                untranscribed.append((audio, session))
    elif args.session:
        from notekeeper.config import DATA_DIR
        session = DATA_DIR / args.session
        if not session.exists():
            print(f"Sesión no encontrada: {args.session}")
            sys.exit(1)
        audio = get_audio_path(session)
        if not audio:
            print(f"No hay audio en {session}")
            sys.exit(1)
        untranscribed = [(audio, session)]
    else:
        untranscribed = find_untranscribed()

    if not untranscribed:
        print("No hay audios sin transcribir.")
        return

    print(f"=== Notekeeper - Transcribir ({len(untranscribed)} archivos) ===\n")

    model = load_model()

    for audio_path, session in untranscribed:
        print(f"\n--- {session.name} ---")
        result = transcribe_file(audio_path, model=model)

        transcript_text = format_transcript(result)
        save_transcript(session, transcript_text, result["segments"])
        save_metadata(session, {
            "language": result["language"],
            "segments_count": len(result["segments"]),
            "transcribed": True,
        })

        print(f"Guardado en {session.name}/transcript.txt")


def cmd_list(args):
    from notekeeper.recorder import list_recordings
    from notekeeper.storage import list_sessions

    if getattr(args, "tag", None):
        tags = [args.tag]
    else:
        tags = getattr(args, "tags", None) or None
    sessions = list_sessions(tags=tags) if tags else None
    list_recordings(sessions=sessions)


def main():
    parser = argparse.ArgumentParser(
        prog="notekeeper",
        description="CLI para grabar y transcribir reuniones",
    )
    sub = parser.add_subparsers(dest="command", help="Comandos disponibles")

    # rec
    rec = sub.add_parser("rec", help="Grabar audio")
    rec.add_argument("-t", "--duration", type=int, help="Duración en segundos")
    rec.add_argument("-d", "--device", type=str, help="Índice o nombre del dispositivo")
    rec.add_argument("-m", "--add-mic", action="store_true", help="Mezclar micrófono + audio de sistema")
    rec.add_argument("--mic", type=str, help="Dispositivo de micrófono para la mezcla")
    rec.add_argument("-l", "--list", action="store_true", help="Listar dispositivos")
    rec.add_argument("-o", "--output", type=str, help="Nombre de sesión de salida")
    rec.add_argument("--tags", nargs="+", help="Tags/contextos de la reunión")
    rec.add_argument("extra", nargs="*", help="Tokens extra (#tags se extraen automáticamente)")

    # transcript
    tr = sub.add_parser("transcript", help="Transcribir audios pendientes")
    tr.add_argument("-s", "--session", type=str, help="ID de sesión específica")
    tr.add_argument("--tag", type=str, help="Solo transcribir sesiones con este tag")

    # list
    li = sub.add_parser("list", help="Listar grabaciones")
    li.add_argument("--tag", type=str, help="Filtrar por tag/contexto")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "rec": cmd_rec,
        "transcript": cmd_transcript,
        "list": cmd_list,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()