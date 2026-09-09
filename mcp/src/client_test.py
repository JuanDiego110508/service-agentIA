"""
Cliente de prueba para verificar el servidor MCP de herramientas matemáticas sobre Streamable HTTP.
Lee la configuración automáticamente desde .env (o usa http://127.0.0.1:8000 por defecto).
"""

import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

# Cargar variables de entorno
load_dotenv()

DEFAULT_HOST = os.getenv("HOST", "127.0.0.1")
DEFAULT_PORT = os.getenv("PORT", "8000")
DEFAULT_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"


async def run_client_tests(base_url: str = DEFAULT_URL) -> bool:
    """Ejecuta pruebas sobre las 3 herramientas matemáticas del servidor MCP."""
    mcp_endpoint = f"{base_url.rstrip('/')}/mcp"
    print(f"\n🚀 Conectando al servidor MCP en {mcp_endpoint}...")

    try:
        async with streamable_http_client(mcp_endpoint) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                # 1. Inicialización de sesión
                print("🤝 Realizando handshake de inicialización...")
                init_result = await session.initialize()
                print(f"✅ Inicializado con éxito: Servidor={init_result.server_info.name} (v{init_result.server_info.version})")

                # 2. Listar herramientas
                print("\n📋 Listando herramientas disponibles en el servidor...")
                tools_response = await session.list_tools()
                print(f"📦 Total de herramientas encontradas: {len(tools_response.tools)}")
                for tool in tools_response.tools:
                    print(f"  - 🔧 {tool.name}: {tool.description}")

                print("\n🧪 Ejecutando pruebas sobre las herramientas matemáticas...")

                # 3. Probar herramienta sumar
                print("\n1️⃣  Probando 'sumar' (a: 15.5, b: 24.5)...")
                suma_res = await session.call_tool("sumar", {"a": 15.5, "b": 24.5})
                print("###############", suma_res)
                print(f"   Resultado: {suma_res.content[0].text if suma_res.content else suma_res}")

                # 4. Probar herramienta multiplicar
                print("\n2️⃣  Probando 'multiplicar' (a: 7, b: 8)...")
                mul_res = await session.call_tool("multiplicar", {"a": 7, "b": 8})
                print(f"   Resultado: {mul_res.content[0].text if mul_res.content else mul_res}")

                # 4. Probar herramienta dividir
                print("\n2️⃣  Probando 'dividir' (a: 20, b: 4)...")
                div_res = await session.call_tool("dividir", {"a": 20, "b": 4})
                print(f"   Resultado: {div_res.content[0].text if div_res.content else div_res}")

                # 5. Probar herramienta potenciacion
                print("\n3️⃣  Probando 'potenciacion' (base: 2, exponente: 10)...")
                pot_res = await session.call_tool("potenciacion", {"base": 2, "exponente": 10})
                print(f"   Resultado: {pot_res.content[0].text if pot_res.content else pot_res}")

                print("\n🎉 ¡Todas las pruebas de matemáticas finalizaron con éxito!")
                return True

    except Exception as exc:
        print(f"\n❌ Error durante la ejecución de las pruebas: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def main() -> None:
    server_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    success = asyncio.run(run_client_tests(server_url))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
