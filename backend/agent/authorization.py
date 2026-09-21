"""
Autorizacion por-usuario para las acciones del agente que MUTAN datos
(generar/eliminar cronograma, aprobar inscripciones, crear evaluaciones).

Por que existe este modulo
---------------------------
Las herramientas MCP (mcp/src/server.py) llaman a la API de World Dance
siempre con la cuenta de servicio del agente (WD_AGENT_EMAIL/PASSWORD), nunca
con la identidad de quien esta chateando. El backend real (ReportAccessGuard
en ms-reporting-analytics-service, el check equivalente en
SchedulingService.generateSchedule, etc.) solo sabe autorizar "es el dueno del
evento o tiene rol ADMIN ahi" -- y para esas herramientas, el "usuario
autenticado" que ve el backend es siempre el agente. Si la cuenta del agente
fue activada como ADMIN en un evento (ver POST
/enrollments/event/{eventId}/agent-admin, que cualquier dueno de evento puede
invocar), CUALQUIERA que chatee con el asistente compartido puede aprovechar
ese acceso para mutar datos de un evento ajeno con solo nombrarlo -- un caso
clasico de "confused deputy".

Este modulo re-valida, del lado del proceso Flask/CrewAI (antes de dejar que
la herramienta llegue a la API real), que la persona real detras del chat
-- identificada por el JWT que ya envia el navegador en cada request a
/api/chat -- sea ella misma dueña o admin del evento en cuestion. Usa
exactamente los mismos endpoints que ya consulta el frontend
(EventService.getEventById, EnrollmentService.getUserEventRole), con el
token real del usuario, para que la respuesta sea la misma que obtendria si
lo hiciera desde la UI.

Postura de seguridad: igual que ReportAccessGuard (backend Java), en caso de
duda (token invalido, red caida, respuesta inesperada) esto NIEGA el acceso;
nunca lo concede por defecto.
"""

import base64
import binascii
import json
import os
import sys

import requests

WD_API_BASE_URL = os.getenv("WD_API_BASE_URL", "https://api.worlddance.win/api/v1")
_REQUEST_TIMEOUT_SECONDS = 10

# Mismas variantes de nombre de campo que event-normalize.ts (frontend) --
# el backend no es consistente en el casing/nombre entre microservicios.
_OWNER_ID_KEYS = ("ownerId", "OwnerId", "organizerId", "OrganizerId", "userId", "UserId")
_ADMIN_ROLE_VALUES = {"admin"}


class AuthorizationError(Exception):
    """Mensaje en español, listo para devolver como resultado de la tool."""


def decode_user_id(token: str | None) -> int | None:
    """Extrae el claim `userId` del JWT sin verificar la firma -- igual que
    TokenService.decodeToken() en el frontend. Es seguro para este uso: el
    valor solo se usa para decidir A CUAL usuario preguntarle su rol; la
    llamada de verificacion real reenvia el mismo token a la API de World
    Dance, que sí valida la firma y rechaza uno falsificado."""
    if not token:
        return None
    try:
        payload_segment = token.split(".")[1]
        padding = "=" * (-len(payload_segment) % 4)
        payload = base64.urlsafe_b64decode(payload_segment + padding)
        claims = json.loads(payload)
        user_id = claims.get("userId")
        return int(user_id) if user_id is not None else None
    except (IndexError, ValueError, binascii.Error, json.JSONDecodeError):
        return None


def _bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _get_json(url: str, token: str) -> dict | None:
    try:
        response = requests.get(url, headers=_bearer_headers(token), timeout=_REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        print(f"[authz] Fallo de red consultando {url}: {exc}", file=sys.stderr)
        return None
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        print(f"[authz] {url} devolvio HTTP {response.status_code}", file=sys.stderr)
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _resolve_event_owner_id(event_id: int, token: str) -> int | None:
    body = _get_json(f"{WD_API_BASE_URL}/events/{event_id}", token)
    if body is None:
        return None
    # Algunos endpoints envuelven en {"data": {...}}, otros devuelven el DTO plano.
    event = body.get("data") if isinstance(body.get("data"), dict) else body
    for key in _OWNER_ID_KEYS:
        if event.get(key) is not None:
            try:
                return int(event[key])
            except (TypeError, ValueError):
                return None
    return None


def _resolve_role_in_event(event_id: int, user_id: int, token: str) -> str | None:
    body = _get_json(f"{WD_API_BASE_URL}/enrollments/events/{event_id}/users/{user_id}/role", token)
    if not body:
        return None
    role = body.get("roleInEvent")
    return str(role) if role is not None else None


def resolve_event_id_for_enrollment(enrollment_id: int, token: str) -> int | None:
    """wd_gestionar_inscripcion solo recibe enrollmentId: hace falta resolver
    a que evento pertenece esa inscripcion para poder autorizar por evento."""
    body = _get_json(f"{WD_API_BASE_URL}/enrollments/{enrollment_id}", token)
    if not body:
        return None
    event_id = body.get("eventId")
    try:
        return int(event_id) if event_id is not None else None
    except (TypeError, ValueError):
        return None


def is_owner_or_admin_of_event(event_id: int, user_id: int, token: str) -> bool:
    owner_id = _resolve_event_owner_id(event_id, token)
    if owner_id is not None and owner_id == user_id:
        return True
    role = _resolve_role_in_event(event_id, user_id, token)
    return bool(role) and role.strip().lower() in _ADMIN_ROLE_VALUES


def require_event_authorization(event_id: int, token: str | None) -> None:
    """Lanza AuthorizationError (mensaje en español para el usuario del chat)
    si quien esta chateando no es dueño ni admin del evento indicado."""
    user_id = decode_user_id(token)
    if user_id is None:
        raise AuthorizationError(
            "No se pudo verificar tu sesión para realizar esta acción. Inicia sesión e inténtalo de nuevo."
        )
    if not is_owner_or_admin_of_event(event_id, user_id, token):  # type: ignore[arg-type]
        raise AuthorizationError(
            f"No tienes permisos de organizador o administrador sobre el evento {event_id}, "
            "así que no puedo realizar esta acción ahí. Pídele al dueño del evento que te asigne "
            "un rol o que active al agente para ese evento."
        )


def require_enrollment_authorization(enrollment_id: int, token: str | None) -> None:
    user_id = decode_user_id(token)
    if user_id is None:
        raise AuthorizationError(
            "No se pudo verificar tu sesión para realizar esta acción. Inicia sesión e inténtalo de nuevo."
        )
    event_id = resolve_event_id_for_enrollment(enrollment_id, token)  # type: ignore[arg-type]
    if event_id is None:
        raise AuthorizationError(
            f"No se pudo verificar a qué evento pertenece la inscripción {enrollment_id}, así que no puedo "
            "gestionarla por seguridad."
        )
    if not is_owner_or_admin_of_event(event_id, user_id, token):  # type: ignore[arg-type]
        raise AuthorizationError(
            f"No tienes permisos de organizador o administrador sobre el evento {event_id} "
            f"(dueño de la inscripción {enrollment_id}), así que no puedo aprobarla ni rechazarla."
        )
