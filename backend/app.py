"""
Servidor Flask - API REST del Agente Conversacional CrewAI + MCP.
"""

import os
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from agent.conversational_agent import process_message, get_history, clear_history

# Configurar Flask para que sirva la carpeta frontend estáticamente
frontend_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
app = Flask(__name__, static_folder=frontend_folder, static_url_path="/")
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route("/")
def serve_frontend():
    """Sirve el archivo index.html del frontend al entrar a la raíz."""
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/status", methods=["GET"])
def status():
    """Estado del servidor MCP y LLM."""
    return jsonify({
        "status": "online",
        "mcp": {"online": True, "mode": "stdio (subproceso automático)"},
        "llm": {"model": "gemini-1.5-flash"}
    })


@app.route("/api/chat", methods=["POST"])
def chat():
    """Endpoint que ejecuta un turno en el bucle del agente."""
    data = request.get_json() or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Mensaje requerido"}), 400

    # El interceptor Angular ya adjunta el Bearer del usuario real a toda
    # request (incluida esta, aunque vaya al backend del agente y no a la API
    # de World Dance). Se reenvía a process_message para que las tools que
    # mutan datos puedan revalidar los permisos de quien está chateando, en
    # vez de confiar solo en la cuenta de servicio del agente (ver
    # agent/authorization.py).
    auth_header = request.headers.get("Authorization", "")
    user_token = auth_header[len("Bearer "):] if auth_header.startswith("Bearer ") else None

    response = process_message(message, user_token=user_token)
    return jsonify({
        "success": True,
        "response": response
    })


@app.route("/api/history", methods=["GET"])
def history():
    """Retorna el historial de conversación persistido."""
    return jsonify({"messages": get_history()})


@app.route("/api/history/clear", methods=["POST"])
def clear():
    """Limpia el historial de conversación."""
    clear_history()
    return jsonify({"success": True})


@app.route("/generate-report-narrative", methods=["POST"])
def generate_report_narrative():
    """Genera narrativa para los reportes desde ms-reports."""
    import requests
    
    data = request.get_json() or {}
    api_key = os.getenv("GEMINI_API_KEY", "")
    
    if not api_key:
        return jsonify({
            "introduccion": "Generado (modo fallback, falta API KEY). El evento se realizó con éxito.",
            "analisisPorModalidad": "No se pudo realizar el análisis por falta de API KEY.",
            "conclusion": "Por favor configure GEMINI_API_KEY en el entorno."
        })
        
    prompt = (
        "Actúa como un experto analista deportivo de baile (World Dance). "
        "A partir de los siguientes datos del evento, redacta 3 secciones precisas en formato JSON estricto "
        "(sin markdown) con las claves: 'introduccion', 'analisisPorModalidad', 'conclusion'.\n"
        f"Datos del evento: {json.dumps(data, ensure_ascii=False)}\n"
        "La introduccion debe ser un resumen ejecutivo formal.\n"
        "El analisisPorModalidad debe detallar tendencias, puntajes promedios y participación.\n"
        "La conclusion debe ser alentadora y enfocada al cierre del evento."
    )
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"}
    }
    
    try:
        r = requests.post(url, json=payload, timeout=20)
        r.raise_for_status()
        candidates = r.json().get("candidates", [])
        if candidates:
            raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return jsonify(json.loads(raw_text.strip()))
    except Exception as e:
        print(f"Error generando narrativa: {e}")
        
    return jsonify({
        "introduccion": f"El evento '{data.get('eventName', 'Desconocido')}' se ejecutó con {data.get('totalParticipants', 0)} participantes.",
        "analisisPorModalidad": f"Puntaje promedio: {data.get('overallAverageScore', 0)}. Alto: {data.get('highestScore', 0)}. Bajo: {data.get('lowestScore', 0)}.",
        "conclusion": "El evento concluyó exitosamente."
    })


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    print(f"Servidor Flask API en http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
