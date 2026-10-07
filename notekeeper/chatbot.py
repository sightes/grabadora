"""Chatbot con interfaz de terminal estilo opencode."""
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.box import MINIMAL, SIMPLE

from notekeeper.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, DATA_DIR
from notekeeper.storage import list_sessions, load_metadata, get_tags

console = Console()

# ── Colores ───────────────────────────────────────────────────
CYAN = "#22D3EE"
VIOLET = "#A78BFA"
GRAY = "#6B7280"
YELLOW = "#F59E0B"
RED = "#EF4444"
DIM = "#4B5563"
GREEN = "#34D399"
MUTED = "#9CA3AF"

DIVIDER = f"[{DIM}]─────────────────────────────────────────────────────────[/]"


def _prompt(text: str) -> str:
    """Muestra prompt con Rich y captura input."""
    console.print(f"  [{CYAN}]{text}[/]", end="")
    return input(" ").strip()


def _print_header():
    console.print()
    console.print(f"  [{VIOLET}]apuntes[{GRAY}] v0.1[/]")
    console.print(f"  [{DIM}]genera apuntes desde tus transcripciones[/]")
    console.print()


def _print_help():
    cmds = [
        ("/apuntes",   "seleccionar transcripciones y generar apuntes"),
        ("/limpiar",   "limpiar historial de conversación"),
        ("/modelo",    "ver modelo configurado"),
        ("/ayuda",     "mostrar esta ayuda"),
        ("/salir",     "salir del chat"),
    ]
    console.print()
    for cmd, desc in cmds:
        console.print(f"    [{YELLOW}]{cmd:<14}[{MUTED}]{desc}[/]")
    console.print()


def get_llm_config():
    return {
        "api_key": LLM_API_KEY,
        "base_url": LLM_BASE_URL,
        "model": LLM_MODEL,
    }


def call_openrouter(messages: list[dict], config: dict) -> str:
    payload = json.dumps({
        "model": config["model"],
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4096,
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
        "HTTP-Referer": "https://github.com/sightes/grabadora",
        "X-Title": "notekeeper-chat",
    }

    req = urllib.request.Request(
        config["base_url"].rstrip("/") + "/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices") or []
            if not choices:
                return "(el modelo no devolvió una respuesta)"
            message = choices[0].get("message") or {}
            return message.get("content") or "(respuesta vacía)"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        return f"error http {exc.code}: {body}"
    except Exception as exc:
        return f"error: {exc}"


def get_transcript_text(session: Path) -> str | None:
    transcript = session / "transcript.txt"
    if transcript.exists():
        return transcript.read_text(encoding="utf-8")
    return None


def select_transcripts() -> list[Path]:
    sessions = list_sessions()

    if not sessions:
        console.print(f"  [{RED}]no hay transcripciones disponibles[/]")
        return []

    sessions_ok = [s for s in sessions if (s / "transcript.txt").exists()]

    if not sessions_ok:
        console.print(f"  [{RED}]no hay transcripciones completadas[/]")
        return []

    table = Table(
        box=SIMPLE,
        show_header=True,
        header_style=f"bold {MUTED}",
        border_style=DIM,
        pad_edge=False,
        padding=(0, 1),
    )
    table.add_column("#", style=CYAN, width=3, justify="right")
    table.add_column("fecha", style=CYAN)
    table.add_column("tags", style=VIOLET)
    table.add_column("dur", style=DIM, justify="right")

    for i, s in enumerate(sessions_ok, 1):
        meta = load_metadata(s)
        tags = get_tags(s)
        tags_str = ", ".join(sorted(tags)) if tags else ""
        duration = meta.get("duration", 0)
        dur_str = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "?"

        try:
            date_str = s.name[:10]
            time_str = s.name[11:16].replace("-", ":")
            display_date = f"{date_str} {time_str}"
        except Exception:
            display_date = s.name

        table.add_row(str(i), display_date, tags_str, dur_str)

    console.print()
    console.print(table)
    console.print()

    selection = _prompt("selecciona")
    if not selection:
        return []
    if selection.lower() == "todas":
        return sessions_ok

    try:
        indices = [int(x.strip()) for x in selection.split(",")]
        selected = []
        for idx in indices:
            if 1 <= idx <= len(sessions_ok):
                selected.append(sessions_ok[idx - 1])
            else:
                console.print(f"  [{RED}]índice inválido: {idx}[/]")
        return selected
    except ValueError:
        console.print(f"  [{RED}]formato inválido[/]")
        return []


def generate_apuntes(sessions: list[Path], config: dict) -> str:
    contents = []
    for s in sessions:
        text = get_transcript_text(s)
        if text:
            tags = get_tags(s)
            tags_str = ", ".join(sorted(tags)) if tags else "sin tags"
            try:
                date_str = s.name[:10]
            except Exception:
                date_str = s.name
            contents.append(f"## {date_str} ({tags_str})\n\n{text[:8000]}")

    if not contents:
        return "no se encontró contenido en las transcripciones seleccionadas."

    context = "\n\n---\n\n".join(contents)

    system_prompt = """Eres un asistente académico experto que genera apuntes de clase estructurados y claros.

INSTRUCCIONES:
- Genera apuntes completos y bien organizados
- Usa formato Markdown con encabezados, bullets y negritas
- Incluye los conceptos clave, definiciones y ejemplos mencionados
- Organiza por temas/subtemas
- Incluye resumen al final
- Si hay ejercicios o problemas mencionados, inclúyelos
- Marca puntos importantes con ⭐
- Usa español claro y conciso

FORMATO DE SALIDA:
# Apuntes de Clase

## Resumen
[resumen general]

## Conceptos Clave
- ...

## Desarrollo
### Tema 1
- ...

## Puntos Importantes
- ...

## Ejercicios/Problemas (si aplica)
- ...

## Resumen Final
- ..."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Genera apuntes de clase basados en estas transcripciones:\n\n{context}"}
    ]

    return call_openrouter(messages, config)


def run_chatbot():
    config = get_llm_config()

    if not config["api_key"]:
        console.print(f"\n  [{RED}]error:[/] LLM_API_KEY no configurado")
        console.print(f"  [{DIM}]agrega tu api key de openrouter en .env[/]\n")
        return

    _print_header()
    console.print(f"  [{DIM}]modelo[{GRAY}] {config['model']}[/]")
    console.print(f"  [{DIM}]escribe[{YELLOW}] /ayuda[{DIM}] para ver comandos[/]")
    console.print()

    history: list[dict] = []
    system_prompt = (
        "Eres un asistente académico que ayuda a estudiantes a entender "
        "y organizar sus clases. Responde de forma clara, concisa y útil. "
        "Si el usuario pregunta sobre apuntes o transcripciones, "
        "sugiere usar el comando /apuntes."
    )

    while True:
        try:
            user_input = _prompt(">")

            if not user_input:
                continue

            # ── Comandos ──────────────────────────────────────
            if user_input.startswith("/"):
                cmd = user_input.lower()

                if cmd == "/salir":
                    console.print(f"\n  [{DIM}]bye[/]\n")
                    break

                elif cmd == "/ayuda":
                    _print_help()
                    continue

                elif cmd == "/limpiar":
                    history.clear()
                    console.print(f"  [{GREEN}]historial limpiado[/]")
                    continue

                elif cmd == "/modelo":
                    console.print(f"\n  [{DIM}]modelo[{GRAY}] {config['model']}[/]")
                    console.print(f"  [{DIM}]url[{GRAY}] {config['base_url']}[/]\n")
                    continue

                elif cmd == "/apuntes":
                    console.print(f"\n  [{YELLOW}]apuntes[/]")
                    console.print(DIVIDER)
                    sessions = select_transcripts()

                    if not sessions:
                        continue

                    console.print(f"\n  [{DIM}]generando apuntes de {len(sessions)} transcripción(es)...[/]")

                    with console.status(f"  [{VIOLET}]procesando[/]", spinner="dots"):
                        apuntes = generate_apuntes(sessions, config)

                    console.print()
                    console.print(Panel(
                        Markdown(apuntes),
                        border_style=DIM,
                        box=MINIMAL,
                        padding=(1, 2),
                    ))

                    console.print()
                    save = _prompt("guardar en archivo? (s/n)")
                    if save in ("s", "si", "y", "yes", ""):
                        try:
                            date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
                            filename = f"apuntes_{date_str}.md"
                        except Exception:
                            filename = "apuntes.md"

                        save_dir = sessions[0].parent if sessions else DATA_DIR
                        filepath = save_dir / filename
                        filepath.write_text(apuntes, encoding="utf-8")
                        console.print(f"  [{GREEN}]guardado[{DIM}] {filepath}[/]")

                    console.print()
                    history.append({"role": "user", "content": "/apuntes"})
                    history.append({"role": "assistant", "content": apuntes})
                    continue

                else:
                    console.print(f"  [{RED}]comando no reconocido:[/] {cmd}")
                    console.print(f"  [{DIM}]escribe[{YELLOW}] /ayuda[/]")
                    continue

            # ── Conversación ──────────────────────────────────
            history.append({"role": "user", "content": user_input})

            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(history[-10:])

            with console.status(f"  [{VIOLET}]pensando[/]", spinner="dots"):
                response = call_openrouter(messages, config)

            console.print()
            console.print(Panel(
                Markdown(response),
                border_style=DIM,
                box=MINIMAL,
                padding=(0, 2),
            ))
            console.print()

            history.append({"role": "assistant", "content": response})

        except KeyboardInterrupt:
            console.print(f"\n\n  [{DIM}]bye[/]\n")
            break
        except EOFError:
            console.print(f"\n\n  [{DIM}]bye[/]\n")
            break