"""
Servidor Flask - API REST del Agente Conversacional CrewAI + MCP.
"""

import os
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

    response = process_message(message)
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


if __name__ == "__main__":
    print("Servidor Flask API en http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
