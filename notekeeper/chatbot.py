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
from rich.text import Text
from rich.table import Table
from rich.box import MINIMAL, SIMPLE, ROUNDED

from notekeeper.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, DATA_DIR
from notekeeper.storage import list_sessions, load_metadata, get_tags

console = Console()

# ── Colores (estilo opencode: monocromático con acentos) ─────
C = {
    "prompt":    "#22D3EE",   # cyan brillante para input
    "user":      "#22D3EE",   # cyan
    "assistant": "#A78BFA",   # violeta
    "system":    "#6B7280",   # gris
    "accent":    "#F59E0B",   # amarillo
    "error":     "#EF4444",   # rojo
    "dim":       "#4B5563",   # gris oscuro
    "border":    "#374151",   # borde sutil
    "muted":     "#9CA3AF",   # gris claro
    "success":   "#34D399",   # verde
}

DIVIDER = f"[{C['dim']}]─────────────────────────────────────────────────────────[/]"


def _print_header():
    """Header minimalista estilo opencode."""
    console.print()
    console.print(f"  [{C['assistant']}]apuntes[{C['system']}] v0.1[/]")
    console.print(f"  [{C['dim']}]genera apuntes desde tus transcripciones[/]")
    console.print()


def _print_help():
    """Ayuda compacta."""
    cmds = [
        ("/apuntes",   "seleccionar transcripciones y generar apuntes"),
        ("/limpiar",   "limpiar historial de conversación"),
        ("/modelo",    "ver modelo configurado"),
        ("/ayuda",     "mostrar esta ayuda"),
        ("/salir",     "salir del chat"),
    ]
    console.print()
    for cmd, desc in cmds:
        console.print(f"    [{C['accent']}]{cmd:<14}[{C['muted']}]{desc}[/]")
    console.print()


def get_llm_config():
    return {
        "api_key": LLM_API_KEY,
        "base_url": LLM_BASE_URL,
        "model": LLM_MODEL,
    }


def call_openrouter(messages: list[dict], config: dict) -> str:
    """Llama a la API de OpenRouter."""
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
    """Menú de selección de transcripciones."""
    sessions = list_sessions()

    if not sessions:
        console.print(f"  [{C['error']}]no hay transcripciones disponibles[/]")
        return []

    sessions_ok = [s for s in sessions if (s / "transcript.txt").exists()]

    if not sessions_ok:
        console.print(f"  [{C['error']}]no hay transcripciones completadas[/]")
        return []

    # Tabla compacta
    table = Table(
        box=SIMPLE,
        show_header=True,
        header_style=f"bold {C['muted']}",
        border_style=C["dim"],
        pad_edge=False,
        padding=(0, 1),
    )
    table.add_column("#", style=C["accent"], width=3, justify="right")
    table.add_column("fecha", style=C["user"])
    table.add_column("tags", style=C["assistant"])
    table.add_column("dur", style=C["dim"], justify="right")

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

    selection = input(f"  [{C['prompt']}]selecciona[{C['dim']}] (1,2,3 o 'todas')[/] > ").strip()

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
                console.print(f"  [{C['error']}]índice inválido: {idx}[/]")
        return selected
    except ValueError:
        console.print(f"  [{C['error']}]formato inválido[/]")
        return []


def generate_apuntes(sessions: list[Path], config: dict) -> str:
    """Genera apuntes desde las transcripciones seleccionadas."""
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
    """Ejecuta el chatbot interactivo."""
    config = get_llm_config()

    if not config["api_key"]:
        console.print(f"\n  [{C['error']}]error:[/] LLM_API_KEY no configurado")
        console.print(f"  [{C['dim']}]agrega tu api key de openrouter en .env[/]\n")
        return

    _print_header()
    console.print(f"  [{C['dim']}]modelo[{C['system']}] {config['model']}[/]")
    console.print(f"  [{C['dim']}]escribe[{C['accent']}] /ayuda[{C['dim']}] para ver comandos[/]")
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
            # Prompt estilo opencode
            user_input = input(f"  [{C['prompt']}]>[/] ").strip()

            if not user_input:
                continue

            # ── Comandos ──────────────────────────────────────
            if user_input.startswith("/"):
                cmd = user_input.lower()

                if cmd == "/salir":
                    console.print(f"\n  [{C['dim']}]bye[/]\n")
                    break

                elif cmd == "/ayuda":
                    _print_help()
                    continue

                elif cmd == "/limpiar":
                    history.clear()
                    console.print(f"  [{C['success']}]historial limpiado[/]")
                    continue

                elif cmd == "/modelo":
                    console.print(f"\n  [{C['dim']}]modelo[{C['system']}] {config['model']}[/]")
                    console.print(f"  [{C['dim']}]url[{C['system']}] {config['base_url']}[/]\n")
                    continue

                elif cmd == "/apuntes":
                    console.print(f"\n  [{C['accent']}]apuntes[/]")
                    console.print(DIVIDER)
                    sessions = select_transcripts()

                    if not sessions:
                        continue

                    console.print(f"\n  [{C['dim']}]generando apuntes de {len(sessions)} transcripción(es)...[/]")

                    with console.status(f"  [{C['assistant']}]procesando[/]", spinner="dots"):
                        apuntes = generate_apuntes(sessions, config)

                    console.print()
                    console.print(Panel(
                        Markdown(apuntes),
                        border_style=C["dim"],
                        box=MINIMAL,
                        padding=(1, 2),
                    ))

                    # Guardar
                    console.print()
                    save = input(f"  [{C['prompt']}]guardar en archivo?[{C['dim']}] (s/n)[/] > ").strip().lower()

                    if save in ("s", "si", "y", "yes", ""):
                        try:
                            date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
                            filename = f"apuntes_{date_str}.md"
                        except Exception:
                            filename = "apuntes.md"

                        save_dir = sessions[0].parent if sessions else DATA_DIR
                        filepath = save_dir / filename
                        filepath.write_text(apuntes, encoding="utf-8")
                        console.print(f"  [{C['success']}]guardado[{C['dim']}] {filepath}[/]")

                    console.print()
                    history.append({"role": "user", "content": "/apuntes"})
                    history.append({"role": "assistant", "content": apuntes})
                    continue

                else:
                    console.print(f"  [{C['error']}]comando no reconocido:[/] {cmd}")
                    console.print(f"  [{C['dim']}]escribe[{C['accent']}] /ayuda[/]")
                    continue

            # ── Conversación normal ───────────────────────────
            history.append({"role": "user", "content": user_input})

            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(history[-10:])

            with console.status(f"  [{C['assistant']}]pensando[/]", spinner="dots"):
                response = call_openrouter(messages, config)

            console.print()
            console.print(Panel(
                Markdown(response),
                border_style=C["dim"],
                box=MINIMAL,
                padding=(0, 2),
            ))
            console.print()

            history.append({"role": "assistant", "content": response})

        except KeyboardInterrupt:
            console.print(f"\n\n  [{C['dim']}]bye[/]\n")
            break
        except EOFError:
            console.print(f"\n\n  [{C['dim']}]bye[/]\n")
            break