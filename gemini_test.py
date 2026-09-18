import os
import requests

API_KEY = os.environ.get("GEMINI_API_KEY")

if not API_KEY:
    print("ERROR: GEMINI_API_KEY not found.")
    exit(1)

url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

headers = {
    "Content-Type": "application/json",
    "x-goog-api-key": API_KEY
}

data = {
    "contents": [
        {
            "parts": [
                {
                    "text": "In one sentence, explain what an Embedded Engineer does."
                }
            ]
        }
    ]
}

response = requests.post(
    url,
    headers=headers,
    json=data,
    timeout=30
)

print("Status:", response.status_code)
print("Response:", response.text)
