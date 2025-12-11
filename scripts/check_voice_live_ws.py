# scripts/check_voice_live_ws.py
import asyncio
import os

import websockets
from dotenv import load_dotenv

async def main():
    load_dotenv()
    endpoint = os.environ["AZURE_AI_FOUNDRY_ENDPOINT"].rstrip("/")
    deployment = os.environ["AZURE_AI_FOUNDRY_DEPLOYMENT"]
    api_version = os.environ.get("AZURE_AI_FOUNDRY_API_VERSION", "2024-10-01-preview")
    uri = f"{endpoint}/openai/realtime?api-version={api_version}&deployment={deployment}"
    print(f"Connecting to {os.environ["AZURE_AI_FOUNDRY_KEY"]}")
    headers = {
        "api-key": os.environ["AZURE_AI_FOUNDRY_KEY"],
        "Ocp-Apim-Subscription-Key": os.environ["AZURE_AI_FOUNDRY_KEY"],
        "Authorization": f"Bearer {os.environ['AZURE_AI_FOUNDRY_KEY']}",
        "OpenAI-Beta": "realtime=v1",
    }
    print("Connecting to", uri)
    try:
        async with websockets.connect(uri.replace("https://", "wss://").replace("http://", "ws://"),
                                      extra_headers=headers,
                                      max_size=None,
                                      ping_interval=None) as ws:
            print("Handshake succeeded:", ws.open)
    except Exception as exc:
        print(type(exc).__name__, exc)

asyncio.run(main())