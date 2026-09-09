import os
import shutil

files_to_remove = [
    r"c:\Users\USUARIO\Downloads\AgenteConversacionalMCP\backend\agent\__init__.py",
    r"c:\Users\USUARIO\Downloads\AgenteConversacionalMCP\mcp\src\__init__.py",
    r"c:\Users\USUARIO\Downloads\AgenteConversacionalMCP\mcp\src\antigravity_mcp\__init__.py"
]

dirs_to_remove = [
    r"c:\Users\USUARIO\Downloads\AgenteConversacionalMCP\mcp\src\antigravity_mcp"
]

for f in files_to_remove:
    try:
        if os.path.exists(f):
            os.remove(f)
            print(f"Deleted {f}")
    except Exception as e:
        print(f"Error deleting {f}: {e}")

for d in dirs_to_remove:
    try:
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"Deleted directory {d}")
    except Exception as e:
        print(f"Error deleting {d}: {e}")
