import os
from google import genai

API_KEY = os.environ.get("GEMINI_API_KEY")

if not API_KEY:
    print("ERROR: GEMINI_API_KEY not found.")
    exit(1)

client = genai.Client(api_key=API_KEY)

try:
    interaction = client.interactions.create(
        model="gemini-3.6-flash",
        input="In one sentence, explain what an Embedded Engineer does."
    )

    print("Status: 200")
    print("Gemini Response:")
    print(interaction.output_text)

except Exception as e:
    print("Gemini API Error:")
    print(e)
    exit(1)
