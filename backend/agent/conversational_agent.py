"""
Agente Conversacional con CrewAI, MCP y herramientas propias.
Implementación directa, legible y concisa con bucle de diálogo y persistencia de historial.
"""

import contextvars
import os
import sys
import json
import threading
import time
from dotenv import load_dotenv

from agent import authorization

# Desactivar telemetría interactiva de CrewAI
os.environ["CREWAI_TRACING_ENABLED"] = "false"
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"

# Cargar variables de entorno desde backend/.env (ruta explícita)
import os
from dotenv import load_dotenv

env_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
print(f"Cargando .env desde: {env_path}")
load_dotenv(dotenv_path=env_path, override=True)

from crewai import Agent, Task, LLM
from crewai.mcp import MCPServerSSE
# -------------------------------------------------------------
# 2. Conexión al Servidor MCP de Matemáticas y Clima
# -------------------------------------------------------------
mcp_server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/sse")

mcp_server = MCPServerSSE(url=mcp_server_url)


# -------------------------------------------------------------
# 3. LLM y Agente Único
# -------------------------------------------------------------
# Extraer exactamente la clave según el proveedor seleccionado
provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
if provider == "gemini":
    api_key = os.getenv("GEMINI_API_KEY", "")
else:
    api_key = os.getenv("OPENAI_API_KEY", "")

if not api_key:
    api_key = "AIza-configura-tu-clave"

llm_model = os.getenv("LLM_MODEL", "gemini/gemini-1.5-flash-latest")
# Si el usuario dejó el default, lo reemplazamos por el que sí encuentra la API
if llm_model == "gemini/gemini-1.5-flash":
    llm_model = "gemini/gemini-1.5-flash-latest"
    
llm = LLM(model=llm_model, api_key=api_key)

assistant = Agent(
    role="Asistente Oficial de World Dance",
    goal="Gestionar cronogramas, inscripciones y reportes de eventos con las herramientas MCP provistas, con precisión y formalidad.",
    backstory=(
        "Asistente oficial de World Dance. Usa siempre tus herramientas MCP para consultar o modificar "
        "datos reales; nunca inventes información. "
        "Si el usuario nombra un evento sin dar su eventId, usa wd_buscar_eventos primero para resolverlo "
        "(1 resultado: úsalo sin preguntar más; varios: pide que confirme cuál; ninguno: pide el nombre "
        "exacto o el id). "
        "Si generar un cronograma falla por falta de inscripciones aprobadas, usa wd_listar_inscripciones "
        "para ver cuáles están pendientes y ofrece aprobarlas con wd_gestionar_inscripcion (pide siempre "
        "confirmación antes de aprobar/rechazar). "
        "Cuando uses wd_exportar_reporte_pdf o wd_exportar_reporte_excel, la herramienta te devuelve un "
        "'Enlace de descarga: <url>'; copia esa URL completa y exacta, carácter por carácter (nunca la "
        "acortes, resumas, omitas, ni la reemplaces por otra), dentro de tu respuesta final, porque el "
        "usuario la necesita para poder descargar el archivo -- si la omites, el usuario no tiene forma de "
        "acceder al reporte. "
        "NUNCA inventes una URL, un dominio (por ejemplo example.com no existe en este sistema) ni un enlace "
        "que no provenga literalmente del texto que te devolvió una herramienta: si una herramienta falla o "
        "no incluye una URL en su respuesta, dilo honestamente ('no se pudo generar el enlace') en vez de "
        "fabricar uno que parezca plausible. "
        "Si una herramienta responde que el usuario no tiene permisos de organizador o administrador sobre "
        "un evento (por ejemplo al generar/eliminar un cronograma o gestionar una inscripción), comunícalo "
        "directamente con el mensaje recibido ('No puedes realizar esta acción, ya que no eres organizador de este evento'); "
        "no inventes justificaciones ni reintentes de otra forma, ya que es una restricción estricta de seguridad. "
        "Responde siempre en español, con tono amable, conciso y profesional, sin emojis, mostrando la "
        "información de las herramientas de forma clara y organizada."
    ),
    tools=[],
    mcps=[mcp_server],
    llm=llm,
    verbose=True
)

# -------------------------------------------------------------
# 3.1 Autorizacion por-usuario para herramientas que MUTAN datos
# -------------------------------------------------------------
# Las herramientas MCP llaman a la API de World Dance con la cuenta de
# servicio del agente (ver mcp/src/server.py), nunca con la identidad de
# quien esta chateando -- si esa cuenta tiene rol ADMIN en un evento ajeno
# (activado por SU dueño via /enrollments/event/{id}/agent-admin), cualquier
# otro usuario podria aprovecharlo para mutar ese evento con solo nombrarlo.
# Antes de dejar pasar una tool que muta datos, se revalida aqui -- con el
# token real de quien esta chateando, no el del agente -- que sea owner o
# admin del evento/inscripcion en cuestion. Ver agent/authorization.py.
_current_user_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_user_token", default=None
)


_execution_lock = threading.Lock()

# Tools que mutan datos de un evento especifico (reciben eventId directo).
_MUTATING_EVENT_TOOLS = {
    "wd_generar_cronograma",
    "wd_actualizar_estado_cronograma",
    "wd_eliminar_cronograma",
    "wd_crear_evaluacion",
}
# wd_gestionar_inscripcion no recibe eventId directamente: hay que resolverlo
# a partir del enrollmentId (ver authorization.require_enrollment_authorization).
_MUTATING_ENROLLMENT_TOOL = "wd_gestionar_inscripcion"


def _guard_event_tool(tool_name: str, original_run):
    def guarded(**kwargs):
        event_id = kwargs.get("eventId")
        try:
            if event_id is None:
                raise authorization.AuthorizationError(
                    f"No se especificó el eventId para {tool_name}; no puedo verificar permisos ni ejecutarla."
                )
            authorization.require_event_authorization(int(event_id), _current_user_token.get())
        except authorization.AuthorizationError as exc:
            print(f"[authz] {tool_name} bloqueada: {exc}", file=sys.stderr)
            return str(exc)
        return original_run(**kwargs)

    return guarded


def _guard_enrollment_tool(tool_name: str, original_run):
    def guarded(**kwargs):
        enrollment_id = kwargs.get("enrollmentId")
        try:
            if enrollment_id is None:
                raise authorization.AuthorizationError(
                    "No se especificó el enrollmentId; no puedo verificar permisos ni ejecutar la acción."
                )
            authorization.require_enrollment_authorization(int(enrollment_id), _current_user_token.get())
        except authorization.AuthorizationError as exc:
            print(f"[authz] {tool_name} bloqueada: {exc}", file=sys.stderr)
            return str(exc)
        return original_run(**kwargs)

    return guarded


# En modo standalone (sin un objeto Crew), debemos inyectar las herramientas del MCP explícitamente:
try:
    mcp_tools = assistant.get_mcp_tools(assistant.mcps)
    for _t in mcp_tools:
        _original_name = getattr(_t, "original_tool_name", None) or _t.name
        if _original_name in _MUTATING_EVENT_TOOLS:
            _t._run = _guard_event_tool(_original_name, _t._run)
        elif _original_name == _MUTATING_ENROLLMENT_TOOL:
            _t._run = _guard_enrollment_tool(_original_name, _t._run)
    assistant.tools.extend(mcp_tools)
except Exception as e:
    print(f"Aviso: No se pudieron cargar las herramientas del MCP ({e})")


# -------------------------------------------------------------
# 4. Historial de la Conversación (Aislado por Usuario)
# -------------------------------------------------------------
HISTORY_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "history")
)

def _get_history_file(user_id: int | str | None = None) -> str:
    """Devuelve la ruta del archivo de historial correspondiente al usuario."""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    if user_id is not None and str(user_id).strip():
        clean_id = "".join(c for c in str(user_id) if c.isalnum() or c in ("-", "_"))
        return os.path.join(HISTORY_DIR, f"user_{clean_id}.json")
    return os.path.join(HISTORY_DIR, "anonymous.json")

def get_history(user_id: int | str | None = None) -> list:
    """Lee el historial de mensajes persistido del usuario."""
    file_path = _get_history_file(user_id)
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_message(user_id: int | str | None, role: str, content: str):
    """Guarda un mensaje en el archivo de historial JSON del usuario."""
    file_path = _get_history_file(user_id)
    history = get_history(user_id)
    history.append({"role": role, "content": content})
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[History] Error guardando historial para usuario {user_id}: {e}", file=sys.stderr)

def clear_history(user_id: int | str | None = None):
    """Limpia el archivo de historial del usuario."""
    file_path = _get_history_file(user_id)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"[History] Error eliminando historial para usuario {user_id}: {e}", file=sys.stderr)


# -------------------------------------------------------------
# 5. Bucle Conversacional y Procesamiento
# -------------------------------------------------------------
# Cuántos turnos previos (usuario + asistente) se incluyen como contexto en cada
# nuevo mensaje, para que el agente tenga memoria real de la conversación. Se
# reenvía completo en CADA llamada al LLM, así que un número más bajo reduce
# directamente el consumo de tokens (configurable sin tocar código).
MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "6"))

# Los mensajes del asistente pueden incluir dumps largos (ej. un cronograma
# completo). Sin recortarlos, cada turno nuevo reenvía ese texto íntegro tantas
# veces como MAX_HISTORY_TURNS, multiplicando el costo en tokens. Se trunca
# solo en el historial que se envía al LLM; el historial persistido (lo que ve
# el usuario en el chat) queda intacto.
MAX_HISTORY_MESSAGE_CHARS = 400


def _build_task_description(user_input: str, user_id: int | str | None = None) -> str:
    """Arma la descripción de la tarea incluyendo los últimos turnos de la
    conversación del usuario específico (antes de agregar el mensaje actual al historial),
    para que el agente recuerde de qué evento/cronograma se viene hablando."""
    history = get_history(user_id)
    recent = history[-(MAX_HISTORY_TURNS * 2):]
    if not recent:
        return user_input

    def _truncate(text: str) -> str:
        text = text or ""
        if len(text) <= MAX_HISTORY_MESSAGE_CHARS:
            return text
        return text[:MAX_HISTORY_MESSAGE_CHARS] + " [...]"

    transcript = "\n".join(
        f"{'Usuario' if entry.get('role') == 'user' else 'Asistente'}: {_truncate(entry.get('content', ''))}"
        for entry in recent
    )

    return (
        "Historial reciente de la conversación (úsalo como contexto, por ejemplo para "
        "recordar el eventId o el cronograma del que se viene hablando):\n"
        f"{transcript}\n\n"
        f"Nuevo mensaje del usuario: {user_input}"
    )


# Reintentos con backoff cuando el proveedor del LLM devuelve un error transitorio
# (ej. 503 UNAVAILABLE / 429 por sobrecarga), en vez de fallar al primer intento.
MAX_LLM_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2  # backoff: 2s, 4s
_TRANSIENT_ERROR_MARKERS = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "overloaded", "high demand")


def _is_transient_error(exc: Exception) -> bool:
    text = str(exc)
    return any(marker in text for marker in _TRANSIENT_ERROR_MARKERS)


def _execute_task_with_retry(task: Task) -> str:
    """Ejecuta la tarea reintentando con backoff si el error parece transitorio
    (sobrecarga del proveedor del LLM). Errores no transitorios se propagan de
    inmediato, sin reintentar."""
    for attempt in range(1, MAX_LLM_RETRIES + 1):
        try:
            return str(assistant.execute_task(task))
        except Exception as exc:
            if attempt == MAX_LLM_RETRIES or not _is_transient_error(exc):
                raise
            delay = RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            print(f"[Retry] Intento {attempt}/{MAX_LLM_RETRIES} falló ({exc}); reintentando en {delay}s...", file=sys.stderr)
            time.sleep(delay)


def process_message(user_input: str, user_token: str | None = None) -> str:
    """Procesa un turno de la conversación y guarda el historial aislado por usuario.

    user_token: el Bearer JWT de quien está chateando (lo reenvía app.py desde
    el header Authorization del navegador). Se usa para aislar el historial
    y para revalidar permisos en las tools mutadoras.
    """
    user_id = authorization.decode_user_id(user_token)
    task_description = _build_task_description(user_input, user_id=user_id)
    save_message(user_id, "user", user_input)

    token_reset = _current_user_token.set(user_token)
    try:
        task = Task(
            description=task_description,
            expected_output="Respuesta conversacional clara y concisa en español.",
            agent=assistant
        )
        with _execution_lock:
            response = _execute_task_with_retry(task)
    except Exception as exc:
        response = f"Error al procesar la solicitud: {exc}"
    finally:
        _current_user_token.reset(token_reset)

    save_message(user_id, "assistant", response)
    return response

def chat():
    """Bucle conversacional interactivo por consola."""
    print("\n[World Dance] Chat con CrewAI + MCP iniciado (escribe 'salir' para terminar):")
    while True:
        user_input = input("Usuario: ").strip()
        if user_input.lower() in ["salir", "exit"]:
            print("Conversación finalizada.")
            break
        if not user_input:
            continue
        
        response = process_message(user_input)
        
        print(f"Asistente: {response}\n")


if __name__ == "__main__":
    chat()
