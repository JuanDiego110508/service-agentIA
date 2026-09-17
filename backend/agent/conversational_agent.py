"""
Agente Conversacional con CrewAI, MCP y herramientas propias.
Implementación directa, legible y concisa con bucle de diálogo y persistencia de historial.
"""

import os
import sys
import json
import time
from dotenv import load_dotenv

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
    goal="Gestionar la creación y consulta de cronogramas y reportes de eventos utilizando las herramientas provistas (MCP). Responder con precision y formalidad.",
    backstory="Eres el asistente conversacional encargado de apoyar en la gestion de los eventos de World Dance. Utilizas siempre tus herramientas MCP para interactuar con los microservicios de generacion de cronogramas y reportes (resultados y evaluaciones). "
    "REGLA CLAVE: casi todas tus herramientas necesitan un eventId numerico, pero los usuarios casi nunca lo conocen y suelen referirse al evento por su NOMBRE (ej. 'Festival de Urban'). "
    "Cuando el usuario mencione un evento por nombre y no te haya dado su id, NUNCA le pidas el id de inmediato: primero usa la herramienta wd_buscar_eventos con ese nombre para resolverlo tu mismo. "
    "Si wd_buscar_eventos devuelve un unico resultado, usa ese id directamente y continua con lo que el usuario pidio, sin preguntar nada mas. "
    "Si devuelve varios resultados, listalos brevemente (nombre y fecha) y pidele al usuario que te confirme cual es. "
    "Solo si wd_buscar_eventos no encuentra ninguna coincidencia, informale que no encontraste un evento con ese nombre y pidele que verifique el nombre o te de el id directamente. "
    "IMPORTANTE: Tu idioma nativo es el español. Responde SIEMPRE de manera amable, fluida, concisa y profesional, sin usar emojis. Cuando uses una herramienta, DEBES responder mostrando de forma clara y organizada la informacion que te devuelva la herramienta en un formato amigable para el usuario.",
    tools=[],
    mcps=[mcp_server],
    llm=llm,
    verbose=True
)

# En modo standalone (sin un objeto Crew), debemos inyectar las herramientas del MCP explícitamente:
try:
    mcp_tools = assistant.get_mcp_tools(assistant.mcps)
    assistant.tools.extend(mcp_tools)
except Exception as e:
    print(f"Aviso: No se pudieron cargar las herramientas del MCP ({e})")


# -------------------------------------------------------------
# 4. Historial de la Conversación
# -------------------------------------------------------------
HISTORY_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "history", "conversacion.json")
)

def get_history() -> list:
    """Lee el historial de mensajes persistido."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_message(role: str, content: str):
    """Guarda un mensaje en el archivo de historial JSON."""
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    history = get_history()
    history.append({"role": role, "content": content})
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def clear_history():
    """Limpia el archivo de historial."""
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)


# -------------------------------------------------------------
# 5. Bucle Conversacional y Procesamiento
# -------------------------------------------------------------
# Cuántos turnos previos (usuario + asistente) se incluyen como contexto en cada
# nuevo mensaje, para que el agente tenga memoria real de la conversación.
MAX_HISTORY_TURNS = 10


def _build_task_description(user_input: str) -> str:
    """Arma la descripción de la tarea incluyendo los últimos turnos de la
    conversación (antes de agregar el mensaje actual al historial), para que
    el agente recuerde de qué evento/cronograma se viene hablando."""
    history = get_history()
    recent = history[-(MAX_HISTORY_TURNS * 2):]
    if not recent:
        return user_input

    transcript = "\n".join(
        f"{'Usuario' if entry.get('role') == 'user' else 'Asistente'}: {entry.get('content', '')}"
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


def process_message(user_input: str) -> str:
    """Procesa un turno de la conversación y guarda el historial."""
    task_description = _build_task_description(user_input)
    save_message("user", user_input)

    try:
        task = Task(
            description=task_description,
            expected_output="Respuesta conversacional clara y concisa en español.",
            agent=assistant
        )
        response = _execute_task_with_retry(task)
    except Exception as exc:
        response = f"Error al procesar la solicitud: {exc}"

    save_message("assistant", response)
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
