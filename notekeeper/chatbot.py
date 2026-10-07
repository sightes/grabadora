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
        ("/apuntes",    "seleccionar transcripciones y generar apuntes"),
        ("/tareas",     "generar tareas y ejercicios desde transcripciones"),
        ("/preguntas",  "listar todas las preguntas realizadas en clase"),
        ("/comunicados","listar comunicados de actividades del doctorado"),
        ("/pruebas",    "resumen de todo lo dicho sobre evaluación"),
        ("/errores",    "identificar errores metodológicos y conceptuales"),
        ("/limpiar",    "limpiar historial de conversación"),
        ("/modelo",     "ver modelo configurado"),
        ("/ayuda",      "mostrar esta ayuda"),
        ("/salir",      "salir del chat"),
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
        "max_tokens": 8192,
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


def get_transcript_text(path: Path) -> str | None:
    """Lee transcripción: puede ser archivo .txt directo o dentro de sesión."""
    if path.is_file() and path.suffix == ".txt":
        return path.read_text(encoding="utf-8")
    if path.is_dir():
        transcript = path / "transcript.txt"
        if transcript.exists():
            return transcript.read_text(encoding="utf-8")
    return None


def _find_transcripts() -> list[Path]:
    """Busca transcripciones en formato sesión y formato directo."""
    results = []

    # 1. Formato sesión: recordings/YYYY-MM-DD_HH-MM-SS/transcript.txt
    for s in list_sessions():
        if (s / "transcript.txt").exists():
            results.append(s)

    # 2. Formato directo: recordings/*.txt (junto a .m4a/.wav)
    data_dir = Path(DATA_DIR)
    if data_dir.exists():
        for txt in sorted(data_dir.glob("*.txt"), reverse=True):
            if txt not in results:
                results.append(txt)

    return results


def select_transcripts() -> list[Path]:
    sessions_ok = _find_transcripts()

    if not sessions_ok:
        console.print(f"  [{RED}]no hay transcripciones disponibles[/]")
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
    table.add_column("nombre", style=CYAN)
    table.add_column("dur", style=DIM, justify="right")

    for i, p in enumerate(sessions_ok, 1):
        if p.is_dir():
            # Formato sesión
            meta = load_metadata(p)
            duration = meta.get("duration", 0)
            dur_str = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "?"
            try:
                display = f"{p.name[:10]} {p.name[11:16].replace('-', ':')}"
            except Exception:
                display = p.name
        else:
            # Formato directo: archivo .txt
            display = p.stem
            # Buscar archivo de audio asociado para duración
            for ext in (".m4a", ".wav", ".mp3", ".ogg"):
                audio = p.with_suffix(ext)
                if audio.exists():
                    dur_str = f"{audio.stat().st_size // 1000000}MB"
                    break
            else:
                dur_str = "?"

        table.add_row(str(i), display, dur_str)

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
    for p in sessions:
        text = get_transcript_text(p)
        if text:
            if p.is_dir():
                # Formato sesión
                tags = get_tags(p)
                tags_str = ", ".join(sorted(tags)) if tags else "sin tags"
                try:
                    name = p.name[:10]
                except Exception:
                    name = p.name
            else:
                # Formato directo: archivo .txt
                name = p.stem
                tags_str = ""
            label = f"{name} ({tags_str})" if tags_str else name
            contents.append(f"## {label}\n\n{text[:15000]}")

    if not contents:
        return "no se encontró contenido en las transcripciones seleccionadas."

    context = "\n\n---\n\n".join(contents)

    system_prompt = """Eres un asistente académico experto que genera apuntes de clase EXTENSOS y DETALLADOS a partir de transcripciones de audio.

INSTRUCCIONES ESTRICTAS:
- Extrae TODA la información relevante de la transcripción, no resumas demasiado
- Incluye definiciones exactas mencionadas por el profesor
- Copia fórmulas, ecuaciones y expresiones matemáticas tal cual se mencionan
- Incluye ejemplos específicos explicados en clase con sus resultados
- Anota procedimientos paso a paso cuando se explican
- Incluye referencias a libros, capítulos o páginas si se mencionan
- Captura las aclaraciones y "tips" que da el profesor
- Incluye preguntas de los alumnos y sus respuestas si son relevantes
- Si se mencionan exámenes, fechas o tareas, inclúyelos
- Organiza TODO por temas/subtemas con jerarquía clara
- Usa viñetas para cada punto, no párrafos largos
- Marca con ⭐ lo que el profesor enfatiza como importante para el examen
- Marca con ⚠️ las aclaraciones o correcciones importantes

FORMATO DE SALIDA OBLIGATORIO:

# 📚 Apuntes de Clase: [Tema Principal]

## 📋 Resumen Ejecutivo
- [3-5 puntos clave de toda la clase]

## 📅 Información de la Clase
- Fecha: [si se menciona]
- Tema: [tema principal]
- Profesor: [si se menciona]
- Referencias: [libros, capítulos, páginas si se mencionan]

---

## 🔑 Conceptos Fundamentales

### Concepto 1: [Nombre]
- **Definición:** [definición exacta mencionada]
- **Fórmula:** [si aplica]
- **Ejemplo:** [ejemplo específico de clase]

### Concepto 2: [Nombre]
- ...

---

## 📖 Desarrollo Detallado

### Tema 1: [Nombre del tema]
#### Subtema 1.1: [Nombre]
- Punto detallado 1
- Punto detallado 2
- **Ejemplo resuelto:** [paso a paso]

#### Subtema 1.2: [Nombre]
- ...

### Tema 2: [Nombre del tema]
- ...

---

## 🧮 Fórmulas y Ecuaciones
| Concepto | Fórmula | Notas |
|----------|---------|-------|
| ... | ... | ... |

---

## ✅ Ejercicios y Problemas Resueltos

### Ejercicio 1: [Descripción]
1. **Enunciado:** [problema]
2. **Datos:** [datos dados]
3. **Resolución:**
   - Paso 1: ...
   - Paso 2: ...
4. **Resultado:** [respuesta final]

---

## ⭐ Puntos Importantes para el Examen
- [todo lo que el profesor marcó como importante]
- [preguntas frecuentes mencionadas]

## ⚠️ Aclaraciones y Correcciones
- [errores comunes mencionados]
- [tips del profesor]

## 📝 Tareas y Expendientes
- [tareas, fechas, trabajos mencionados]

---

## 🎯 Resumen Final
- [lista de los puntos más importantes para recordar]"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Genera apuntes de clase basados en estas transcripciones:\n\n{context}"}
    ]

    return call_openrouter(messages, config)


def generate_tareas(sessions: list[Path], config: dict) -> str:
    """Genera tareas/ejercicios desde las transcripciones seleccionadas."""
    contents = []
    for p in sessions:
        text = get_transcript_text(p)
        if text:
            if p.is_dir():
                tags = get_tags(p)
                tags_str = ", ".join(sorted(tags)) if tags else ""
                try:
                    name = p.name[:10]
                except Exception:
                    name = p.name
            else:
                name = p.stem
                tags_str = ""
            label = f"{name} ({tags_str})" if tags_str else name
            contents.append(f"## {label}\n\n{text[:15000]}")

    if not contents:
        return "no se encontró contenido en las transcripciones seleccionadas."

    context = "\n\n---\n\n".join(contents)

    system_prompt = """Eres un asistente académico experto que genera tareas y ejercicios de práctica basados en clases grabadas.

INSTRUCCIONES ESTRICTAS:
- Genera ejercicios que cubran TODOS los temas vistos en clase
- Incluye ejercicios de diferentes niveles: básico, intermedio, avanzado
- Si el profesor mencionó ejercicios específicos, inclúyelos tal cual
- Si hay ejemplos resueltos en clase, genera ejercicios similares con otros datos
- Incluye las respuestas/respuestas esperadas al final de cada ejercicio
- Marca con 🟢 básico, 🟡 intermedio, 🔴 avanzado
- Si se mencionaron tareas o exámenes, inclúyelos
- Incluye ejercicios de tipo examen si es posible

FORMATO DE SALIDA OBLIGATORIO:

# 📝 Tareas y Ejercicios

## 📋 Resumen de Temas Cubiertos
- [lista de temas que se practican]

---

## Ejercicios de Práctica

### 🟢 Nivel Básico

#### Ejercicio 1: [Título]
**Tema:** [tema que practica]
**Enunciado:**
[problema completo]

**Datos:**
- [dato 1]
- [dato 2]

**Resolución:**
1. [paso 1]
2. [paso 2]
3. ...

**Respuesta:** [resultado final]

---

### 🟡 Nivel Intermedio

#### Ejercicio N: [Título]
...

---

### 🔴 Nivel Avanzado

#### Ejercicio N: [Título]
...

---

## 📋 Tareas del Profesor (si se mencionaron)
- [tarea 1 con fecha]
- [tarea 2]

## 💡 Tips para Resolver
- [consejos basados en lo explicado en clase]
- [errores comunes a evitar]"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Genera tareas y ejercicios de práctica basados en estas transcripciones de clase:\n\n{context}"}
    ]

    return call_openrouter(messages, config)


def generate_preguntas(sessions: list[Path], config: dict) -> str:
    """Extrae todas las preguntas realizadas en clase."""
    contents = []
    for p in sessions:
        text = get_transcript_text(p)
        if text:
            if p.is_dir():
                tags = get_tags(p)
                tags_str = ", ".join(sorted(tags)) if tags else ""
                try:
                    name = p.name[:10]
                except Exception:
                    name = p.name
            else:
                name = p.stem
                tags_str = ""
            label = f"{name} ({tags_str})" if tags_str else name
            contents.append(f"## {label}\n\n{text[:15000]}")

    if not contents:
        return "no se encontró contenido en las transcripciones seleccionadas."

    context = "\n\n---\n\n".join(contents)

    system_prompt = """Eres un asistente académico que extrae y organiza todas las preguntas realizadas durante una clase.

INSTRUCCIONES ESTRICTAS:
- Identifica TODAS las preguntas hechas por alumnos o por el profesor
- Incluye el contexto de la pregunta (qué se estaba explicando)
- Si la pregunta fue respondida, incluye la respuesta
- Clasifica las preguntas por tipo: conceptual, procedimental, aclaración
- Si una pregunta generó discusión, incluye los puntos clave
- Mantén el lenguaje original de la transcripción
- Incluye timestamps si están disponibles en la transcripción

FORMATO DE SALIDA OBLIGATORIO:

# ❓ Preguntas de Clase

## 📋 Resumen
- Total de preguntas: [N]
- Temas más preguntados: [lista]

---

## Preguntas por Tema

### 📚 Tema 1: [Nombre del tema]

#### ❓ Pregunta 1
**Contexto:** [qué se estaba explicando]
**Pregunta:** [pregunta exacta]
**Respuesta:** [respuesta si se dio]

#### ❓ Pregunta 2
**Contexto:** [...]
**Pregunta:** [...]
**Respuesta:** [...]

---

### 📚 Tema 2: [Nombre del tema]
...

---

## 🔍 Preguntas sin Respuesta Clara
- [preguntas que quedaron sin respuesta o con respuesta ambigua]

## 💡 Preguntas Clave para el Examen
- [preguntas que el profesor marcó como importantes]

## 📝 Notas Adicionales
- [cualquier observación relevante sobre las preguntas]"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Extrae y organiza todas las preguntas realizadas en estas clases:\n\n{context}"}
    ]

    return call_openrouter(messages, config)


def generate_comunicados(sessions: list[Path], config: dict) -> str:
    """Extrae comunicados sobre actividades del doctorado."""
    contents = []
    for p in sessions:
        text = get_transcript_text(p)
        if text:
            if p.is_dir():
                try:
                    name = p.name[:10]
                except Exception:
                    name = p.name
            else:
                name = p.stem
            contents.append(f"## {name}\n\n{text[:15000]}")

    if not contents:
        return "no se encontró contenido en las transcripciones seleccionadas."

    context = "\n\n---\n\n".join(contents)

    system_prompt = """Eres un asistente académico que extrae comunicados oficiales de actividades de doctorado mencionados en clases.

INSTRUCCIONES ESTRICTAS:
- Identifica TODOS los comunicados mencionados por el profesor o coordinación
- Incluye fechas, plazos y requisitos mencionados
- Organiza por categorías: exámenes, inscripciones, plazos, eventos, requisitos
- Si hay fechas límite, márcalas claramente
- Incluye información de contacto si se menciona
- Si un comunicado es urgente o tiene fecha próxima, márcalo
- Captura información sobre: tesis, seminarios, publicaciones, defensas, cursos

FORMATO DE SALIDA OBLIGATORIO:

# 📢 Comunicados del Doctorado

## 📋 Resumen
- Total de comunicados: [N]
- Próximos plazos: [lista breve]

---

## 📅 Próximas Fechas Importantes

| Fecha | Actividad | Estado |
|-------|-----------|--------|
| [fecha] | [actividad] | ⚠️ urgente / 📌 próximo / ✅ sin fecha |

---

## 📝 Comunicados por Categoría

### 🎓 Exámenes y Defensas
- [comunicado 1 con fecha y detalles]
- [comunicado 2]

### 📚 Inscripciones y Matrícula
- [comunicado 1]

### 📄 Publicaciones y Requisitos
- [comunicado 1]

### 📆 Eventos y Seminarios
- [comunicado 1]

### 📋 Tesis y Proyecto de Investigación
- [comunicado 1]

---

## ⚠️ Acciones Requeridas
- [lista de cosas que el alumno debe hacer con fecha límite]

## 📞 Contactos y Referencias
- [emails, teléfonos, oficinas mencionadas]

## 📌 Notas Adicionales
- [cualquier información relevante adicional]"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Extrae todos los comunicados sobre actividades del doctorado mencionados en estas clases:\n\n{context}"}
    ]

    return call_openrouter(messages, config)


def generate_pruebas(sessions: list[Path], config: dict) -> str:
    """Genera resumen de todo lo dicho sobre evaluación."""
    contents = []
    for p in sessions:
        text = get_transcript_text(p)
        if text:
            if p.is_dir():
                try:
                    name = p.name[:10]
                except Exception:
                    name = p.name
            else:
                name = p.stem
            contents.append(f"## {name}\n\n{text[:15000]}")

    if not contents:
        return "no se encontró contenido en las transcripciones seleccionadas."

    context = "\n\n---\n\n".join(contents)

    system_prompt = """Eres un asistente académico que extrae y resume TODO lo mencionado sobre evaluación en clases.

INSTRUCCIONES ESTRICTAS:
- Busca TODAS las menciones de: pruebas, exámenes, evaluaciones, notas, calificaciones, rubrica, porcentajes
- Incluye fechas de evaluaciones si se mencionan
- Incluye formato de las pruebas (oral, escrita, múltiple opción, ensayo, etc.)
- Incluye porcentajes o pesos de cada evaluación si se mencionan
- Incluye temas que entran en cada evaluación
- Incluye recomendaciones del profesor para prepararse
- Incluye preguntas de los alumnos sobre evaluaciones y sus respuestas
- Si se mencionan criterios de evaluación o rúbricas, inclúyelos
- Si hay cambios o actualizaciones en la evaluación, márcalos

FORMATO DE SALIDA OBLIGATORIO:

# 📊 Todo sobre Evaluación

## 📋 Resumen General
- Total de menciones sobre evaluación: [N]
- Próximas evaluaciones: [lista breve]

---

## 📅 Cronograma de Evaluaciones

| Evaluación | Fecha | Temas | Porcentaje | Formato |
|------------|-------|-------|------------|---------|
| [nombre] | [fecha] | [temas] | [%] | [formato] |

---

## 📝 Detalle por Evaluación

### 📌 Evaluación 1: [Nombre]
- **Fecha:** [fecha]
- **Formato:** [oral/escrita/etc.]
- **Temas que entran:** [lista de temas]
- **Porcentaje:** [% de la nota final]
- **Criterios de evaluación:** [rúbrica si se menciona]
- **Recomendaciones del profesor:** [tips]

### 📌 Evaluación 2: [Nombre]
...

---

## 📚 Distribución de Notas
- [porcentajes de cada evaluación si se mencionaron]

## 💡 Recomendaciones para Estudiar
- [tips y consejos del profesor]

## ❓ Preguntas sobre Evaluación
- [preguntas de alumnos sobre evaluaciones con respuestas]

## ⚠️ Notas Importantes
- [cualquier cambio, actualización o advertencia]"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Extrae y resume TODO lo mencionado sobre evaluación en estas clases:\n\n{context}"}
    ]

    return call_openrouter(messages, config)


def generate_errores(sessions: list[Path], config: dict) -> str:
    """Identifica errores metodológicos y conceptuales en las clases."""
    contents = []
    for p in sessions:
        text = get_transcript_text(p)
        if text:
            if p.is_dir():
                try:
                    name = p.name[:10]
                except Exception:
                    name = p.name
            else:
                name = p.stem
            contents.append(f"## {name}\n\n{text[:15000]}")

    if not contents:
        return "no se encontró contenido en las transcripciones seleccionadas."

    context = "\n\n---\n\n".join(contents)

    system_prompt = """Eres un experto académico que identifica errores metodológicos, conceptuales y didácticos en clases grabadas.

INSTRUCCIONES ESTRICTAS:
- Analiza la transcripción buscando errores de cualquier tipo
- Clasifica cada error por tipo y gravedad
- Incluye el contexto exacto donde ocurre el error
- Proporciona la corrección correcta cuando sea posible
- Sé objetivo y profesional, no critiques al profesor sino al contenido
- Si no estás seguro de si es un error, márcalo como "posible error" o "verificar"
- Incluye tanto errores del profesor como conceptos erróneos de alumnos que no fueron corregidos

TIPOS DE ERRORES A BUSCAR:
1. **Conceptuales:** Definiciones incorrectas, conceptos mal explicados
2. **Metodológicos:** Procedimientos incorrectos, pasos omitidos
3. **Numéricos:** Cálculos erróneos, fórmulas mal aplicadas
4. **Terminológicos:** Uso incorrecto de términos técnicos
5. **Didácticos:** Explicaciones confusas, ejemplos incorrectos
6. **Referencias:** Citas incorrectas, atribuciones erróneas

FORMATO DE SALIDA OBLIGATORIO:

# ⚠️ Errores Identificados en Clase

## 📋 Resumen
- Total de errores encontrados: [N]
- Por tipo:
  - Conceptuales: [N]
  - Metodológicos: [N]
  - Numéricos: [N]
  - Otros: [N]

---

## 🔴 Errores Conceptuales

### Error 1: [Breve descripción]
- **Contexto:** [qué se estaba explicando]
- **Error:** [qué se dijo incorrectamente]
- **Corrección:** [lo correcto]
- **Gravedad:** Alta/Media/Baja

### Error 2: ...
...

---

## 🟠 Errores Metodológicos

### Error 1: [Breve descripción]
- **Contexto:** [...]
- **Error:** [procedimiento incorrecto]
- **Corrección:** [procedimiento correcto]
- **Gravedad:** Alta/Media/Baja

---

## 🟡 Errores Numéricos

### Error 1: [Breve descripción]
- **Cálculo incorrecto:** [...]
- **Cálculo correcto:** [...]

---

## 🔵 Errores Terminológicos

### Error 1: [Término usado] → [Término correcto]
- **Contexto:** [...]

---

## 🟢 Conceptos No Corregidos

- [conceptos erróneos dichos por alumnos que no fueron corregidos]

---

## 💡 Notas Adicionales
- [observaciones sobre la calidad metodológica general]
- [patrones de errores recurrentes]"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Identifica todos los errores metodológicos, conceptuales y didácticos en estas clases:\n\n{context}"}
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

                        save_dir = sessions[0].parent if sessions and sessions[0].is_dir() else DATA_DIR
                        filepath = save_dir / filename
                        filepath.write_text(apuntes, encoding="utf-8")
                        console.print(f"  [{GREEN}]guardado[{DIM}] {filepath}[/]")

                    console.print()
                    history.append({"role": "user", "content": "/apuntes"})
                    history.append({"role": "assistant", "content": apuntes})
                    continue

                elif cmd == "/tareas":
                    console.print(f"\n  [{YELLOW}]tareas[/]")
                    console.print(DIVIDER)
                    sessions = select_transcripts()

                    if not sessions:
                        continue

                    console.print(f"\n  [{DIM}]generando tareas de {len(sessions)} transcripción(es)...[/]")

                    with console.status(f"  [{VIOLET}]procesando[/]", spinner="dots"):
                        tareas = generate_tareas(sessions, config)

                    console.print()
                    console.print(Panel(
                        Markdown(tareas),
                        border_style=DIM,
                        box=MINIMAL,
                        padding=(1, 2),
                    ))

                    console.print()
                    save = _prompt("guardar en archivo? (s/n)")
                    if save in ("s", "si", "y", "yes", ""):
                        try:
                            date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
                            filename = f"tareas_{date_str}.md"
                        except Exception:
                            filename = "tareas.md"

                        save_dir = sessions[0].parent if sessions and sessions[0].is_dir() else DATA_DIR
                        filepath = save_dir / filename
                        filepath.write_text(tareas, encoding="utf-8")
                        console.print(f"  [{GREEN}]guardado[{DIM}] {filepath}[/]")

                    console.print()
                    history.append({"role": "user", "content": "/tareas"})
                    history.append({"role": "assistant", "content": tareas})
                    continue

                elif cmd == "/preguntas":
                    console.print(f"\n  [{YELLOW}]preguntas[/]")
                    console.print(DIVIDER)
                    sessions = select_transcripts()

                    if not sessions:
                        continue

                    console.print(f"\n  [{DIM}]extrayendo preguntas de {len(sessions)} transcripción(es)...[/]")

                    with console.status(f"  [{VIOLET}]procesando[/]", spinner="dots"):
                        preguntas = generate_preguntas(sessions, config)

                    console.print()
                    console.print(Panel(
                        Markdown(preguntas),
                        border_style=DIM,
                        box=MINIMAL,
                        padding=(1, 2),
                    ))

                    console.print()
                    save = _prompt("guardar en archivo? (s/n)")
                    if save in ("s", "si", "y", "yes", ""):
                        try:
                            date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
                            filename = f"preguntas_{date_str}.md"
                        except Exception:
                            filename = "preguntas.md"

                        save_dir = sessions[0].parent if sessions and sessions[0].is_dir() else DATA_DIR
                        filepath = save_dir / filename
                        filepath.write_text(preguntas, encoding="utf-8")
                        console.print(f"  [{GREEN}]guardado[{DIM}] {filepath}[/]")

                    console.print()
                    history.append({"role": "user", "content": "/preguntas"})
                    history.append({"role": "assistant", "content": preguntas})
                    continue

                elif cmd == "/comunicados":
                    console.print(f"\n  [{YELLOW}]comunicados[/]")
                    console.print(DIVIDER)
                    sessions = select_transcripts()

                    if not sessions:
                        continue

                    console.print(f"\n  [{DIM}]extrayendo comunicados de {len(sessions)} transcripción(es)...[/]")

                    with console.status(f"  [{VIOLET}]procesando[/]", spinner="dots"):
                        comunicados = generate_comunicados(sessions, config)

                    console.print()
                    console.print(Panel(
                        Markdown(comunicados),
                        border_style=DIM,
                        box=MINIMAL,
                        padding=(1, 2),
                    ))

                    console.print()
                    save = _prompt("guardar en archivo? (s/n)")
                    if save in ("s", "si", "y", "yes", ""):
                        try:
                            date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
                            filename = f"comunicados_{date_str}.md"
                        except Exception:
                            filename = "comunicados.md"

                        save_dir = sessions[0].parent if sessions and sessions[0].is_dir() else DATA_DIR
                        filepath = save_dir / filename
                        filepath.write_text(comunicados, encoding="utf-8")
                        console.print(f"  [{GREEN}]guardado[{DIM}] {filepath}[/]")

                    console.print()
                    history.append({"role": "user", "content": "/comunicados"})
                    history.append({"role": "assistant", "content": comunicados})
                    continue

                elif cmd == "/pruebas":
                    console.print(f"\n  [{YELLOW}]pruebas[/]")
                    console.print(DIVIDER)
                    sessions = select_transcripts()

                    if not sessions:
                        continue

                    console.print(f"\n  [{DIM}]extrayendo info sobre evaluación de {len(sessions)} transcripción(es)...[/]")

                    with console.status(f"  [{VIOLET}]procesando[/]", spinner="dots"):
                        pruebas = generate_pruebas(sessions, config)

                    console.print()
                    console.print(Panel(
                        Markdown(pruebas),
                        border_style=DIM,
                        box=MINIMAL,
                        padding=(1, 2),
                    ))

                    console.print()
                    save = _prompt("guardar en archivo? (s/n)")
                    if save in ("s", "si", "y", "yes", ""):
                        try:
                            date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
                            filename = f"pruebas_{date_str}.md"
                        except Exception:
                            filename = "pruebas.md"

                        save_dir = sessions[0].parent if sessions and sessions[0].is_dir() else DATA_DIR
                        filepath = save_dir / filename
                        filepath.write_text(pruebas, encoding="utf-8")
                        console.print(f"  [{GREEN}]guardado[{DIM}] {filepath}[/]")

                    console.print()
                    history.append({"role": "user", "content": "/pruebas"})
                    history.append({"role": "assistant", "content": pruebas})
                    continue

                elif cmd == "/errores":
                    console.print(f"\n  [{YELLOW}]errores[/]")
                    console.print(DIVIDER)
                    sessions = select_transcripts()

                    if not sessions:
                        continue

                    console.print(f"\n  [{DIM}]analizando errores en {len(sessions)} transcripción(es)...[/]")

                    with console.status(f"  [{VIOLET}]procesando[/]", spinner="dots"):
                        errores = generate_errores(sessions, config)

                    console.print()
                    console.print(Panel(
                        Markdown(errores),
                        border_style=DIM,
                        box=MINIMAL,
                        padding=(1, 2),
                    ))

                    console.print()
                    save = _prompt("guardar en archivo? (s/n)")
                    if save in ("s", "si", "y", "yes", ""):
                        try:
                            date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
                            filename = f"errores_{date_str}.md"
                        except Exception:
                            filename = "errores.md"

                        save_dir = sessions[0].parent if sessions and sessions[0].is_dir() else DATA_DIR
                        filepath = save_dir / filename
                        filepath.write_text(errores, encoding="utf-8")
                        console.print(f"  [{GREEN}]guardado[{DIM}] {filepath}[/]")

                    console.print()
                    history.append({"role": "user", "content": "/errores"})
                    history.append({"role": "assistant", "content": errores})
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