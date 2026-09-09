import os
from dotenv import load_dotenv

_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".env"))
print("Loading from:", _env_path)
load_dotenv(dotenv_path=_env_path, override=True)

print("LLM_PROVIDER:", os.getenv("LLM_PROVIDER"))
print("GEMINI_API_KEY:", os.getenv("GEMINI_API_KEY"))
print("OPENAI_API_KEY:", os.getenv("OPENAI_API_KEY"))
