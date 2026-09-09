# Servidor MCP en Python (Matemáticas con transporte HTTP / SSE)

Este repositorio contiene una implementación de un servidor **MCP (Model Context Protocol)** desarrollado en Python utilizando la librería oficial de MCP (`mcp>=2.0.0`), enfocado en herramientas matemáticas. Toda la lógica del servidor y sus herramientas reside directamente en **`src/server.py`** y la configuración se gestiona a través del archivo **`.env`**.

---

## 🌟 Herramientas Incluidas

| Herramienta | Parámetros | Descripción | Ejemplo |
| :--- | :--- | :--- | :--- |
| `sumar` | `a: float, b: float` | Suma dos números ($a + b$). | `sumar(a=15.5, b=24.5)` $\rightarrow$ `40.0` |
| `multiplicar` | `a: float, b: float` | Multiplica dos números ($a \times b$). | `multiplicar(a=7, b=8)` $\rightarrow$ `56.0` |
| `potenciacion`| `base: float, exponente: float` | Eleva una base a su exponente ($base^{exponente}$). | `potenciacion(base=2, exponente=10)` $\rightarrow$ `1024.0` |

---

## 📁 Estructura del Proyecto

```
antigravity-mcp/
├── requirements.txt            # Dependencias gestionadas con pip
├── .env                        # Variables de entorno activas
├── .env.example                # Plantilla de variables de entorno
├── README.md                   # Documentación técnica
└── src/
    ├── __init__.py
    ├── server.py               # Servidor MCP con la definición y lógica de las herramientas
    └── client_test.py          # Cliente de prueba para verificar las 3 herramientas
```

---

## ⚙️ Configuración (`.env`)

En el archivo [`.env`](file:///home/german/Documents/CodeBase/antigravity-mcp/.env):

```env
# Protocolo de transporte: 'sse' (HTTP), 'streamable-http' o 'stdio'
TRANSPORT=sse

# Configuración de Red
HOST=127.0.0.1
PORT=8000
```

---

## 🚀 Inicio Rápido con `pip`

### 1. Activar entorno e instalar dependencias

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Iniciar el Servidor MCP

```bash
python3 src/server.py
```

### 3. Probar con el Cliente de Prueba

En otra terminal:
```bash
python3 src/client_test.py
```

---

## 🔌 Configuración en Clientes MCP

### Conexión HTTP / SSE:
```json
{
  "mcpServers": {
    "math-tools": {
      "url": "http://127.0.0.1:8000/sse"
    }
  }
}
```

### Conexión Local STDIO (con `TRANSPORT=stdio` en `.env`):
```json
{
  "mcpServers": {
    "math-tools": {
      "command": "python3",
      "args": [
        "/ruta/completa/a/antigravity-mcp/src/server.py"
      ]
    }
  }
}
```
