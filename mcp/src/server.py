"""
Servidor MCP en Python con transporte HTTP (SSE) y herramientas para World Dance.
Utilizando FastMCP (la interfaz oficial y recomendada del SDK de MCP).
"""

import os
import sys
from typing import Any, List

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Cargar variables de entorno desde .env
load_dotenv()

# Configuración leída desde variables de entorno (.env)
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
TRANSPORT = os.getenv("TRANSPORT", "sse").lower().strip()
WD_API_BASE_URL = os.getenv("WD_API_BASE_URL", "https://api.worlddance.win")
WD_BEARER_TOKEN = os.getenv("WD_BEARER_TOKEN", "")

def get_auth_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if WD_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {WD_BEARER_TOKEN}"
    return headers

# Inicializar FastMCP
# host/port se pasan aqui (no despues via mcp.settings) porque FastMCP solo
# auto-configura la proteccion DNS-rebinding (allowed_hosts=localhost/127.0.0.1)
# cuando el host de construccion es localhost. Como el servidor escucha en
# 0.0.0.0 dentro de Docker y los clientes llegan con Host: service-agentia-mcp,
# construirlo ya con ese host evita que quede una allowlist obsoleta que
# rechace toda conexion con 421 Misdirected Request.
mcp = FastMCP(
    "WorldDanceServer",
    dependencies=["requests"],
    host=HOST,
    port=PORT
)

# -------------------------------------------------------------
# HERRAMIENTAS DE SCHEDULING (CRONOGRAMA)
# -------------------------------------------------------------
@mcp.tool()
def wd_generar_cronograma(
    eventId: int, 
    defaultDurationMinutes: int, 
    transitionMinutes: int, 
    sortingStrategy: str, 
    stageNames: List[str], 
    notes: str
) -> str:
    """Genera un cronograma inicial para un evento de World Dance. Requiere eventId, defaultDurationMinutes, transitionMinutes, sortingStrategy, stageNames y notes."""
    print(f"[MCP Tool] Ejecutando wd_generar_cronograma para eventId={eventId}", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/scheduling/generate"
    payload = {
        "eventId": eventId,
        "defaultDurationMinutes": defaultDurationMinutes,
        "transitionMinutes": transitionMinutes,
        "sortingStrategy": sortingStrategy,
        "stageNames": stageNames,
        "notes": notes
    }
    try:
        response = requests.post(url, headers=get_auth_headers(), json=payload)
        response.raise_for_status()
        return str(response.json() if response.content else "Cronograma generado exitosamente.")
    except Exception as exc:
        return f"Error al generar cronograma: {str(exc)}"

@mcp.tool()
def wd_obtener_cronograma(eventId: int) -> str:
    """Obtiene el cronograma de un evento de World Dance por su ID (eventId)."""
    print(f"[MCP Tool] Ejecutando wd_obtener_cronograma para eventId={eventId}", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/scheduling/event/{eventId}"
    try:
        response = requests.get(url, headers=get_auth_headers())
        response.raise_for_status()
        return str(response.json())
    except Exception as exc:
        return f"Error al obtener cronograma: {str(exc)}"

@mcp.tool()
def wd_eliminar_cronograma(eventId: int) -> str:
    """Elimina el cronograma de un evento de World Dance por su ID (eventId)."""
    print(f"[MCP Tool] Ejecutando wd_eliminar_cronograma para eventId={eventId}", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/scheduling/event/{eventId}"
    try:
        response = requests.delete(url, headers=get_auth_headers())
        response.raise_for_status()
        return "Cronograma eliminado exitosamente."
    except Exception as exc:
        return f"Error al eliminar cronograma: {str(exc)}"

# -------------------------------------------------------------
# HERRAMIENTAS DE SCORING (REPORTES Y EVALUACIONES)
# -------------------------------------------------------------
@mcp.tool()
def wd_obtener_resultados(eventId: int, modalityId: int) -> str:
    """Obtiene los resultados/reportes de una modalidad en un evento de World Dance."""
    print(f"[MCP Tool] Ejecutando wd_obtener_resultados para eventId={eventId}, modalityId={modalityId}", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/scoring/events/{eventId}/modalities/{modalityId}/results"
    try:
        response = requests.get(url, headers=get_auth_headers())
        response.raise_for_status()
        return str(response.json())
    except Exception as exc:
        return f"Error al obtener resultados: {str(exc)}"

@mcp.tool()
def wd_crear_evaluacion(
    eventId: int, 
    modalityId: int, 
    enrollmentId: int,
    scores: List[dict],
    observations: str
) -> str:
    """Crea una evaluación para una inscripción (enrollmentId) en una modalidad de un evento."""
    print(f"[MCP Tool] Ejecutando wd_crear_evaluacion para enrollmentId={enrollmentId}", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/scoring/events/{eventId}/modalities/{modalityId}/enrollments/{enrollmentId}/evaluations"
    payload = {
        "scores": scores,
        "observations": observations
    }
    try:
        response = requests.post(url, headers=get_auth_headers(), json=payload)
        response.raise_for_status()
        return str(response.json() if response.content else "Evaluación creada.")
    except Exception as exc:
        return f"Error al crear evaluación: {str(exc)}"

@mcp.tool()
def wd_exportar_reporte_pdf(eventId: int) -> str:
    """Exporta y obtiene el enlace o resultado del reporte en formato PDF de un evento."""
    print(f"[MCP Tool] Ejecutando wd_exportar_reporte_pdf para eventId={eventId}", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/reports/events/{eventId}/export/pdf"
    try:
        response = requests.get(url, headers=get_auth_headers())
        response.raise_for_status()
        return f"Reporte PDF exportado/generado. Respuesta: {response.text}"
    except Exception as exc:
        return f"Error al exportar reporte PDF: {str(exc)}"

@mcp.tool()
def wd_exportar_reporte_excel(eventId: int) -> str:
    """Exporta y obtiene el enlace o resultado del reporte en formato Excel de un evento."""
    print(f"[MCP Tool] Ejecutando wd_exportar_reporte_excel para eventId={eventId}", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/reports/events/{eventId}/export/excel"
    try:
        response = requests.get(url, headers=get_auth_headers())
        response.raise_for_status()
        return f"Reporte Excel exportado/generado. Respuesta: {response.text}"
    except Exception as exc:
        return f"Error al exportar reporte Excel: {str(exc)}"

@mcp.tool()
def wd_obtener_ranking_evento(eventId: int) -> str:
    """Obtiene el ranking general de un evento."""
    print(f"[MCP Tool] Ejecutando wd_obtener_ranking_evento para eventId={eventId}", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/reports/events/{eventId}/ranking"
    try:
        response = requests.get(url, headers=get_auth_headers())
        response.raise_for_status()
        return str(response.json())
    except Exception as exc:
        return f"Error al obtener ranking del evento: {str(exc)}"

@mcp.tool()
def wd_obtener_ranking_modalidad(eventId: int, modalityId: int) -> str:
    """Obtiene el ranking específico de una modalidad dentro de un evento."""
    print(f"[MCP Tool] Ejecutando wd_obtener_ranking_modalidad para eventId={eventId}, modalityId={modalityId}", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/reports/events/{eventId}/modalities/{modalityId}/ranking"
    try:
        response = requests.get(url, headers=get_auth_headers())
        response.raise_for_status()
        return str(response.json())
    except Exception as exc:
        return f"Error al obtener ranking de la modalidad: {str(exc)}"


def main() -> None:
    """Punto de entrada principal para ejecutar el servidor MCP."""
    print(f"Iniciando servidor MCP '{mcp.name}' en http://{HOST}:{PORT} (transporte: {TRANSPORT})...")
    # FastMCP maneja el transporte internamente
    if TRANSPORT == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
