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
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.text import Text
from rich.live import Live
from rich.spinner import Spinner
from rich.columns import Columns
from rich.box import HEAVY, ROUNDED, DOUBLE

from notekeeper.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, DATA_DIR
from notekeeper.storage import list_sessions, get_audio_path, load_metadata, get_tags

console = Console()

# ══════════════════════════════════════════════════════════════════════════════
# COLORES Y ESTILOS (estilo opencode)
# ══════════════════════════════════════════════════════════════════════════════
USER_COLOR = "#00D4AA"      # Cyan/verde brillante
ASSISTANT_COLOR = "#A78BFA"  # Violeta suave
SYSTEM_COLOR = "#6B7280"     # Gris
ACCENT_COLOR = "#F59E0B"     # Amarillo/dorado
ERROR_COLOR = "#EF4444"      # Rojo
BORDER_COLOR = "#374151"     # Gris oscuro
PROMPT_COLOR = "#00D4AA"     # Cyan para el prompt
TAG_COLOR = "#60A5FA"        # Azul para tags

BANNER = """[bold #A78BFA]
  ╔═══════════════════════════════════════════════════════════╗
  ║                                                           ║
  ║   ░█▀█░█▀█░█▀▀░█▀█░█▀▀░█▀█░█▀▄░█▀▀                      ║
  ║   ░█░█░█▀▀░█▀▀░█░█░█░░░█░█░█░█░█▀▀                      ║
  ║   ░▀▀▀░▀░░░▀▀▀░▀░▀░▀▀▀░▀▀▀░▀▀░░▀▀▀                      ║
  ║                                                           ║
  ║   [dim]Genera apuntes de clase desde tus transcripciones[/dim]   ║
  ║                                                           ║
  ╚═══════════════════════════════════════════════════════════╝
[/bold #A78BFA]"""

HELP_TEXT = f"""[{SYSTEM_COLOR}]
Comandos disponibles:
  /apuntes     Seleccionar transcripciones y generar apuntes
  /historial   Ver conversación anterior
  /limpiar     Limpiar historial de conversación
  /modelo      Ver modelo actual
  /ayuda       Mostrar esta ayuda
  /salir       Salir del chat

Escribe tu pregunta directamente para conversar con el asistente.
[/]"""


def get_llm_config():
    """Obtiene configuración del LLM desde .env."""
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
                return "(El modelo no devolvió una respuesta)"
            message = choices[0].get("message") or {}
            return message.get("content") or "(Respuesta vacía)"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        return f"[{ERROR_COLOR}]Error HTTP {exc.code}: {body}[/]"
    except Exception as exc:
        return f"[{ERROR_COLOR}]Error: {exc}[/]"


def get_transcript_text(session: Path) -> str | None:
    """Lee el texto de una transcripción."""
    transcript = session / "transcript.txt"
    if transcript.exists():
        return transcript.read_text(encoding="utf-8")
    return None


def select_transcripts() -> list[Path]:
    """Muestra menú para seleccionar transcripciones."""
    sessions = list_sessions()

    if not sessions:
        console.print(f"[{ERROR_COLOR}]No hay transcripciones disponibles.[/]")
        return []

    # Filtrar solo las que tienen transcripción
    sessions_with_transcript = []
    for s in sessions:
        if (s / "transcript.txt").exists():
            sessions_with_transcript.append(s)

    if not sessions_with_transcript:
        console.print(f"[{ERROR_COLOR}]No hay transcripciones completadas.[/]")
        return []

    # Mostrar tabla de transcripciones
    console.print()
    table = Table(
        title="Transcripciones disponibles",
        box=ROUNDED,
        border_style=BORDER_COLOR,
        title_style=f"bold {ACCENT_COLOR}",
        show_lines=True,
    )
    table.add_column("#", style=SYSTEM_COLOR, width=4)
    table.add_column("Fecha", style=TAG_COLOR)
    table.add_column("Tags", style=USER_COLOR)
    table.add_column("Duración", style=SYSTEM_COLOR)
    table.add_column("Estado", style=SYSTEM_COLOR)

    for i, s in enumerate(sessions_with_transcript, 1):
        meta = load_metadata(s)
        tags = get_tags(s)
        tags_str = ", ".join(sorted(tags)) if tags else "-"
        duration = meta.get("duration", 0)
        dur_str = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "?"
        language = meta.get("language", "?")
        segments = meta.get("segments_count", 0)
        status = f"{language} | {segments} seg"

        # Parsear fecha del nombre de la sesión
        try:
            date_str = s.name[:10]
            time_str = s.name[11:16].replace("-", ":")
            display_date = f"{date_str} {time_str}"
        except:
            display_date = s.name

        table.add_row(str(i), display_date, tags_str, dur_str, status)

    console.print(table)
    console.print()

    # Pedir selección
    selection = Prompt.ask(
        f"[{PROMPT_COLOR}]Selecciona transcripciones[/] (ej: 1,2,3 o 'todas')",
        default="1",
    )

    if selection.lower() == "todas":
        return sessions_with_transcript

    try:
        indices = [int(x.strip()) for x in selection.split(",")]
        selected = []
        for idx in indices:
            if 1 <= idx <= len(sessions_with_transcript):
                selected.append(sessions_with_transcript[idx - 1])
            else:
                console.print(f"[{ERROR_COLOR}]Índice inválido: {idx}[/]")
        return selected
    except ValueError:
        console.print(f"[{ERROR_COLOR}]Formato inválido. Usa números separados por coma.[/]")
        return []


def generate_apuntes(sessions: list[Path], config: dict) -> str:
    """Genera apuntes a partir de las transcripciones seleccionadas."""
    # Recopilar contenido de las transcripciones
    contents = []
    for s in sessions:
        text = get_transcript_text(s)
        if text:
            meta = load_metadata(s)
            tags = get_tags(s)
            tags_str = ", ".join(sorted(tags)) if tags else "sin tags"
            try:
                date_str = s.name[:10]
            except:
                date_str = s.name
            contents.append(f"## Transcripción: {date_str} ({tags_str})\n\n{text[:8000]}")

    if not contents:
        return "[{ERROR_COLOR}]No se encontró contenido en las transcripciones seleccionadas.[/]"

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
# 📚 Apuntes de Clase

## 📋 Resumen
[resumen general]

## 🔑 Conceptos Clave
- ...

## 📖 Desarrollo
### Tema 1
- ...

## 💡 Puntos Importantes
- ...

## 📝 Ejercicios/Problemas (si aplica)
- ...

## 🎯 Resumen Final
- ..."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Genera apuntes de clase basados en estas transcripciones:\n\n{context}"}
    ]

    return call_openrouter(messages, config)


def stream_response(text: str):
    """Muestra texto con efecto de escritura."""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
    print()


def run_chatbot():
    """Ejecuta el chatbot interactivo."""
    config = get_llm_config()

    if not config["api_key"]:
        console.print(f"[{ERROR_COLOR}]Error: LLM_API_KEY no configurado en .env[/]")
        console.print(f"[{SYSTEM_COLOR}]Configura tu API key de OpenRouter en el archivo .env[/]")
        return

    # Mostrar banner
    console.print(BANNER)
    console.print(f"[{SYSTEM_COLOR}]Modelo: [{ACCENT_COLOR}]{config['model']}[/]")
    console.print(f"[{SYSTEM_COLOR}]Escribe [{PROMPT_COLOR}]/ayuda[{SYSTEM_COLOR}] para ver comandos[/]")
    console.print()

    # Historial de conversación
    history: list[dict] = []
    system_prompt = """Eres un asistente académico que ayuda a estudiantes a entender y organizar 
    sus clases. Responde de forma clara, concisa y útil. Si el usuario pregunta sobre apuntes 
    o transcripciones, sugiere usar el comando /apuntes."""

    while True:
        try:
            # Prompt del usuario
            user_input = Prompt.ask(f"\n[{PROMPT_COLOR}]tú[/]")

            if not user_input.strip():
                continue

            # Comandos especiales
            if user_input.startswith("/"):
                cmd = user_input.strip().lower()

                if cmd == "/salir":
                    console.print(f"\n[{SYSTEM_COLOR}]¡Hasta luego![/]\n")
                    break

                elif cmd == "/ayuda":
                    console.print(HELP_TEXT)
                    continue

                elif cmd == "/limpiar":
                    history.clear()
                    console.print(f"[{SYSTEM_COLOR}]Historial limpiado.[/]")
                    continue

                elif cmd == "/modelo":
                    console.print(f"\n[{SYSTEM_COLOR}]Modelo actual: [{ACCENT_COLOR}]{config['model']}[/]")
                    console.print(f"[{SYSTEM_COLOR}]URL: [{ACCENT_COLOR}]{config['base_url']}[/]\n")
                    continue

                elif cmd == "/apuntes":
                    console.print(f"\n[{ACCENT_COLOR}]═══ Generador de Apuntes ═══[/]")
                    sessions = select_transcripts()

                    if not sessions:
                        continue

                    console.print(f"\n[{SYSTEM_COLOR}]Generando apuntes de {len(sessions)} transcripción(es)...[/]\n")

                    with console.status(f"[{ACCENT_COLOR}]Procesando...", spinner="dots"):
                        apuntes = generate_apuntes(sessions, config)

                    console.print(Panel(
                        Markdown(apuntes),
                        title="📚 Apuntes de Clase",
                        border_style=ACCENT_COLOR,
                        box=ROUNDED,
                        padding=(1, 2),
                    ))

                    # Preguntar si guardar
                    if Confirm.ask(f"\n[{PROMPT_COLOR}]¿Guardar apuntes en archivo?[/]", default=True):
                        # Generar nombre de archivo
                        try:
                            date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
                            filename = f"apuntes_{date_str}.md"
                        except:
                            filename = "apuntes.md"

                        # Guardar en la carpeta de recordings o en la primera sesión
                        if sessions:
                            save_dir = sessions[0].parent
                        else:
                            save_dir = DATA_DIR

                        filepath = save_dir / filename
                        filepath.write_text(apuntes, encoding="utf-8")
                        console.print(f"[{SYSTEM_COLOR}]Guardado en: [{ACCENT_COLOR}]{filepath}[/]")

                    # Agregar al historial
                    history.append({"role": "user", "content": "/apuntes"})
                    history.append({"role": "assistant", "content": apuntes})
                    continue

                else:
                    console.print(f"[{ERROR_COLOR}]Comando no reconocido: {cmd}[/]")
                    console.print(f"[{SYSTEM_COLOR}]Escribe [{PROMPT_COLOR}]/ayuda[{SYSTEM_COLOR}] para ver comandos[/]")
                    continue

            # Conversación normal con el LLM
            history.append({"role": "user", "content": user_input})

            # Construir mensajes
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(history[-10:])  # Últimos 10 mensajes de contexto

            # Mostrar spinner mientras espera respuesta
            with console.status(f"[{ASSISTANT_COLOR}]Pensando...", spinner="dots"):
                response = call_openrouter(messages, config)

            # Mostrar respuesta
            console.print()
            console.print(Panel(
                Markdown(response),
                title=f"[{ASSISTANT_COLOR}]Asistente[/]",
                border_style=ASSISTANT_COLOR,
                box=ROUNDED,
                padding=(1, 2),
            ))

            history.append({"role": "assistant", "content": response})

        except KeyboardInterrupt:
            console.print(f"\n\n[{SYSTEM_COLOR}]¡Hasta luego![/]\n")
            break
        except EOFError:
            console.print(f"\n\n[{SYSTEM_COLOR}]¡Hasta luego![/]\n")
            break