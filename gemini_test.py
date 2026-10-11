
import os
import sys
from google import genai
from google.genai import types

API_KEY = os.environ.get("GEMINI_API_KEY")

if not API_KEY:
    print("ERROR: GEMINI_API_KEY not found.")
    sys.exit(1)

try:
    client = genai.Client(
        api_key=API_KEY,
        http_options=types.HttpOptions(
            timeout=20000  # 20 seconds
        )
    )

    print("Testing Gemini API...", flush=True)

    interaction = client.interactions.create(
        model="gemini-3.6-flash",
        input="In one sentence, explain what an Embedded Engineer does."
    )

    print("Gemini API test successful!", flush=True)
    print("Gemini Response:", flush=True)
    print(interaction.output_text, flush=True)

except Exception as e:
    print(f"Gemini API test failed: {type(e).__name__}: {e}", flush=True)
    sys.exit(1)
