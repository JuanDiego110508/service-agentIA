"""
Agente Conversacional con CrewAI, MCP y herramientas propias.
Implementación directa, legible y concisa con bucle de diálogo y persistencia de historial.
"""

import os
import json
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
    backstory="Eres el asistente conversacional encargado de apoyar en la gestion de los eventos de World Dance. Utilizas siempre tus herramientas MCP para interactuar con los microservicios de generacion de cronogramas y reportes (resultados y evaluaciones). IMPORTANTE: Tu idioma nativo es el español. Responde SIEMPRE de manera amable, fluida, concisa y profesional, sin usar emojis. Cuando uses una herramienta, DEBES responder mostrando de forma clara y organizada la informacion que te devuelva la herramienta en un formato amigable para el usuario.",
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
def process_message(user_input: str) -> str:
    """Procesa un turno de la conversación y guarda el historial."""
    save_message("user", user_input)

    try:
        task = Task(
            description=user_input,
            expected_output="Respuesta conversacional clara y concisa en español.",
            agent=assistant
        )
        response = str(assistant.execute_task(task))
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
