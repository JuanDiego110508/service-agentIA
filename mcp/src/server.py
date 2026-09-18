"""
Servidor MCP en Python con transporte HTTP (SSE) y herramientas para World Dance.
Utilizando FastMCP (la interfaz oficial y recomendada del SDK de MCP).
"""

import os
import sys
import threading
import time
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
WD_API_BASE_URL = os.getenv("WD_API_BASE_URL", "https://api.worlddance.win/api/v1")
WD_AGENT_EMAIL = os.getenv("WD_AGENT_EMAIL", "")
WD_AGENT_PASSWORD = os.getenv("WD_AGENT_PASSWORD", "")

# -------------------------------------------------------------
# AUTENTICACIÓN DEL AGENTE (cuenta de servicio)
# -------------------------------------------------------------
# En vez de un WD_BEARER_TOKEN fijo (que expira a la hora y hay que renovar
# a mano), el agente se loguea solo con WD_AGENT_EMAIL/WD_AGENT_PASSWORD y
# mantiene el JWT en memoria, refrescándolo antes de que expire.
_token_lock = threading.Lock()
_cached_token: str | None = None
_token_obtained_at: float = 0.0
TOKEN_REFRESH_INTERVAL_SECONDS = 50 * 60  # el JWT dura 1h; refrescamos a los 50 min


def _login() -> str:
    """Inicia sesión con la cuenta de servicio del agente y devuelve un JWT nuevo."""
    if not WD_AGENT_EMAIL or not WD_AGENT_PASSWORD:
        raise RuntimeError("WD_AGENT_EMAIL / WD_AGENT_PASSWORD no están configurados.")
    url = f"{WD_API_BASE_URL}/auth/login"
    response = requests.post(
        url,
        json={"email": WD_AGENT_EMAIL, "password": WD_AGENT_PASSWORD},
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status()
    body = response.json()
    jwt = (body.get("data") or {}).get("jwt")
    if not jwt:
        raise RuntimeError(f"Login del agente falló: {body.get('message', 'respuesta sin token')}")
    return jwt


def _refresh(token: str) -> str:
    """Refresca un JWT existente (funciona incluso si acaba de expirar)."""
    url = f"{WD_API_BASE_URL}/auth/refresh"
    response = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()
    body = response.json()
    jwt = body.get("jwt")
    if not jwt:
        raise RuntimeError("Refresh del agente falló: respuesta sin token")
    return jwt


def get_valid_token() -> str:
    """Devuelve un JWT vigente del agente, logueándose o refrescando según haga falta."""
    global _cached_token, _token_obtained_at
    with _token_lock:
        if _cached_token is None:
            _cached_token = _login()
            _token_obtained_at = time.time()
        elif time.time() - _token_obtained_at > TOKEN_REFRESH_INTERVAL_SECONDS:
            try:
                _cached_token = _refresh(_cached_token)
            except Exception as exc:
                print(f"[Auth] Refresh falló ({exc}), reintentando login...", file=sys.stderr)
                _cached_token = _login()
            _token_obtained_at = time.time()
        return _cached_token


def get_auth_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_valid_token()}",
    }


def _raise_for_status_with_message(response: requests.Response) -> None:
    """Como response.raise_for_status(), pero conserva el mensaje real que devuelve
    el backend (ej. {"message": "El evento no tiene modalidades configuradas."})
    en vez de solo el código HTTP genérico ("400 Client Error: Bad Request ...")."""
    if response.ok:
        return
    detail = None
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = body.get("message") or body.get("error")
    except ValueError:
        pass
    if not detail:
        detail = (response.text or "").strip()[:300] or response.reason
    raise RuntimeError(f"HTTP {response.status_code}: {detail}")

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
# HERRAMIENTAS DE EVENTOS E INSCRIPCIONES
# -------------------------------------------------------------
@mcp.tool()
def wd_buscar_eventos(nombre: str = "") -> str:
    """Busca eventos por nombre (parcial, sin distinguir mayúsculas). Úsala
    SIEMPRE que el usuario dé el nombre de un evento en vez del eventId, para
    resolverlo antes de llamar otra herramienta. nombre vacío = todos.
    Sin coincidencias: pide nombre exacto o id. Varias: pide que confirme cuál."""
    print(f"[MCP Tool] wd_buscar_eventos nombre='{nombre}'", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/events/getEvents"
    try:
        response = requests.get(url, headers=get_auth_headers())
        _raise_for_status_with_message(response)
        events = (response.json() or {}).get("data") or []
        needle = nombre.strip().lower()
        if needle:
            events = [e for e in events if needle in str(e.get("name", "")).lower()]
        return str([
            {"idEvent": e.get("idEvent"), "name": e.get("name"), "status": e.get("status"), "startDate": e.get("startDate")}
            for e in events
        ])
    except Exception as exc:
        return f"Error al buscar eventos: {exc}"


@mcp.tool()
def wd_listar_inscripciones(eventId: int, status: str = "") -> str:
    """Lista las inscripciones de un evento. status opcional: PENDING,
    APPROVED o REJECTED (vacío = todas). Úsala antes de generar un cronograma
    si el usuario pregunta por qué falla, o antes de aprobar/rechazar."""
    print(f"[MCP Tool] wd_listar_inscripciones eventId={eventId} status='{status}'", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/enrollments/event/{eventId}"
    try:
        response = requests.get(url, headers=get_auth_headers())
        _raise_for_status_with_message(response)
        enrollments = response.json() or []
        needle = status.strip().upper()
        if needle:
            enrollments = [e for e in enrollments if str(e.get("status", "")).upper() == needle]
        return str([
            {
                "enrollmentId": e.get("enrollmentId"),
                "modalityId": e.get("modalityId"),
                "status": e.get("status"),
                "participant": (e.get("participant") or {}).get("fullName") or (e.get("participant") or {}).get("name"),
            }
            for e in enrollments
        ])
    except Exception as exc:
        return f"Error al listar inscripciones: {exc}"


@mcp.tool()
def wd_gestionar_inscripcion(enrollmentId: int, status: str, reason: str = "") -> str:
    """Aprueba o rechaza una inscripción (solo si está PENDING). status debe
    ser "APPROVED" o "REJECTED". reason es obligatorio si status="REJECTED".
    Solo puede hacerlo el organizador del evento o el agente si fue activado
    como ADMIN en ese evento."""
    print(f"[MCP Tool] wd_gestionar_inscripcion enrollmentId={enrollmentId} status={status}", file=sys.stderr)
    if status.upper() not in ("APPROVED", "REJECTED"):
        return "Error: status debe ser APPROVED o REJECTED."
    if status.upper() == "REJECTED" and not reason.strip():
        return "Error: debes indicar una razón (reason) para rechazar la inscripción."
    url = f"{WD_API_BASE_URL}/enrollments/approve"
    payload = {"enrollmentId": enrollmentId, "status": status.upper(), "reason": reason or None}
    try:
        response = requests.patch(url, headers=get_auth_headers(), json=payload)
        _raise_for_status_with_message(response)
        return str(response.json() if response.content else "Inscripción actualizada.")
    except Exception as exc:
        return f"Error al gestionar la inscripción: {exc}"


# -------------------------------------------------------------
# HERRAMIENTAS DE SCHEDULING (CRONOGRAMA)
# -------------------------------------------------------------
@mcp.tool()
def wd_generar_cronograma(
    eventId: int,
    defaultDurationMinutes: int = 5,
    transitionMinutes: int = 2,
    sortingStrategy: str = "NEWEST_FIRST",
    modalityOrder: List[int] | None = None,
    stageNames: List[str] | None = None,
    notes: str = "",
) -> str:
    """Genera el cronograma de un evento (solo con inscripciones APPROVED).
    sortingStrategy: NEWEST_FIRST (default), OLDEST_FIRST o ALPHABETICAL.
    modalityOrder: ids de modalidad en el orden deseado (opcional). stageNames:
    escenarios en rotación (opcional, default "Escenario Principal")."""
    print(f"[MCP Tool] Ejecutando wd_generar_cronograma para eventId={eventId}", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/scheduling/generate"
    payload = {
        "eventId": eventId,
        "defaultDurationMinutes": defaultDurationMinutes,
        "transitionMinutes": transitionMinutes,
        "sortingStrategy": sortingStrategy,
        "modalityOrder": modalityOrder,
        "stageNames": stageNames or [],
        "notes": notes,
    }
    try:
        response = requests.post(url, headers=get_auth_headers(), json=payload)
        _raise_for_status_with_message(response)
        return str(response.json() if response.content else "Cronograma generado exitosamente.")
    except Exception as exc:
        return f"Error al generar cronograma: {str(exc)}"

@mcp.tool()
def wd_obtener_cronograma(eventId: int) -> str:
    """Obtiene el cronograma de un evento por su eventId."""
    print(f"[MCP Tool] Ejecutando wd_obtener_cronograma para eventId={eventId}", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/scheduling/event/{eventId}"
    try:
        response = requests.get(url, headers=get_auth_headers())
        _raise_for_status_with_message(response)
        return str(response.json())
    except Exception as exc:
        return f"Error al obtener cronograma: {str(exc)}"

@mcp.tool()
def wd_actualizar_estado_cronograma(eventId: int, status: str) -> str:
    """Actualiza el estado del cronograma (ej. para publicarlo). status:
    "DRAFT", "ACTIVE" o "FINISHED"."""
    print(f"[MCP Tool] Ejecutando wd_actualizar_estado_cronograma para eventId={eventId}, status={status}", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/scheduling/event/{eventId}/status"
    try:
        response = requests.patch(url, headers=get_auth_headers(), params={"status": status})
        _raise_for_status_with_message(response)
        return str(response.json() if response.content else "Estado del cronograma actualizado.")
    except Exception as exc:
        return f"Error al actualizar el estado del cronograma: {str(exc)}"

@mcp.tool()
def wd_eliminar_cronograma(eventId: int) -> str:
    """Elimina el cronograma de un evento por su eventId."""
    print(f"[MCP Tool] Ejecutando wd_eliminar_cronograma para eventId={eventId}", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/scheduling/event/{eventId}"
    try:
        response = requests.delete(url, headers=get_auth_headers())
        _raise_for_status_with_message(response)
        return "Cronograma eliminado exitosamente."
    except Exception as exc:
        return f"Error al eliminar cronograma: {str(exc)}"

# -------------------------------------------------------------
# HERRAMIENTAS DE SCORING (REPORTES Y EVALUACIONES)
# -------------------------------------------------------------
@mcp.tool()
def wd_obtener_resultados(eventId: int, modalityId: int) -> str:
    """Obtiene los resultados/reportes de una modalidad en un evento."""
    print(f"[MCP Tool] Ejecutando wd_obtener_resultados para eventId={eventId}, modalityId={modalityId}", file=sys.stderr)
    url = f"{WD_API_BASE_URL}/scoring/events/{eventId}/modalities/{modalityId}/results"
    try:
        response = requests.get(url, headers=get_auth_headers())
        _raise_for_status_with_message(response)
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
        _raise_for_status_with_message(response)
        return str(response.json() if response.content else "Evaluación creada.")
    except Exception as exc:
        return f"Error al crear evaluación: {str(exc)}"

@mcp.tool()
def wd_exportar_reporte_pdf(eventId: int) -> str:
    """Exporta el reporte en formato PDF de un evento y devuelve el enlace de descarga."""
    print(f"[MCP Tool] Ejecutando wd_exportar_reporte_pdf para eventId={eventId}", file=sys.stderr)
    return _exportar_reporte(eventId, "pdf")

@mcp.tool()
def wd_exportar_reporte_excel(eventId: int) -> str:
    """Exporta el reporte en formato Excel de un evento y devuelve el enlace de descarga."""
    print(f"[MCP Tool] Ejecutando wd_exportar_reporte_excel para eventId={eventId}", file=sys.stderr)
    return _exportar_reporte(eventId, "excel")

def _exportar_reporte(eventId: int, formato: str) -> str:
    """El endpoint de exportacion devuelve el archivo binario (PDF/Excel) directamente,
    no un JSON con un enlace: leerlo con requests y volcarlo a texto (como se hacia antes)
    produce contenido binario ilegible que el LLM no puede reenviar al usuario, y el
    navegador nunca recibe nada descargable. En vez de traer el archivo completo solo para
    descartarlo, se hace un HEAD liviano para confirmar que el reporte esta disponible y se
    devuelve la URL real: el frontend la detecta en la respuesta y la convierte en un boton
    de descarga que vuelve a pedir el archivo con las credenciales del usuario que esta
    chateando (no las de esta cuenta de servicio del agente)."""
    url = f"{WD_API_BASE_URL}/reports/events/{eventId}/export/{formato}"
    try:
        response = requests.head(url, headers=get_auth_headers(), timeout=10)
        if response.status_code >= 400:
            return (
                f"No se pudo confirmar el reporte en {formato.upper()} del evento {eventId} "
                f"(HTTP {response.status_code}). Verifica que el evento exista y tenga datos."
            )
    except Exception as exc:
        # El chequeo previo es best-effort: si falla (timeout, red, o esta cuenta de
        # servicio no tiene permiso sobre ese evento en particular), igual se devuelve la
        # URL -- el usuario real la abrira con su propia sesion, que es la que manda.
        print(f"[MCP Tool] Aviso: no se pudo verificar el reporte ({exc})", file=sys.stderr)

    return (
        f"Reporte en {formato.upper()} listo para el evento {eventId}. "
        f"Enlace de descarga: {url}"
    )

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
