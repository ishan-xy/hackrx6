import os
import json
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

@app.middleware("http")
async def discord_webhook_middleware(request: Request, call_next):
    # Read body (bytes)
    body_bytes = await request.body()
    body_text = body_bytes.decode('utf-8', errors='ignore')

    # Try to parse body as JSON for pretty formatting
    try:
        body_json = json.loads(body_text) if body_text else None
        pretty_body = json.dumps(body_json, indent=2) if body_json else body_text
    except Exception:
        pretty_body = body_text  # fallback to raw text

    # Prepare the content/message to send to Discord
    # Include Authorization header and path + method + body
    headers = dict(request.headers)
    auth_header = headers.get("authorization", "No Authorization header")

    # Truncate body if too long for Discord (2000 char limit)
    max_body_length = 1500  # Leave room for other content
    if len(pretty_body) > max_body_length:
        pretty_body = pretty_body[:max_body_length] + "... (truncated)"

    content = (
        f"**Incoming request:**\n"
        f"**URL:** {request.url}\n"
        f"**Method:** {request.method}\n"
        f"**Authorization:** {auth_header}\n\n"
        f"**Body:**\n```json\n{pretty_body}\n```"
    )

    # Ensure content doesn't exceed Discord's 2000 character limit
    if len(content) > 2000:
        content = content[:1997] + "..."

    # Send message to Discord webhook with httpx async client
    if DISCORD_WEBHOOK_URL:
        async with httpx.AsyncClient() as client:
            try:
                webhook_response = await client.post(
                    DISCORD_WEBHOOK_URL,
                    json={"content": content},
                    timeout=10.0  # Add timeout to prevent hanging
                )
                webhook_response.raise_for_status()  # Raise exception for HTTP errors
            except Exception as e:
                # Log or print but do not block request processing on failure
                print(f"Failed to send Discord webhook: {e}")
    else:
        print("DISCORD_WEBHOOK_URL is not set. Skipping Discord webhook notification.")

    # Re-create the request with the body for downstream processing
    # This is the proper way to handle body consumption in FastAPI middleware
    async def receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    # Override the request's receive method to replay the body
    request._receive = receive
    
    # Continue processing the request normally
    response: Response = await call_next(request)
    return response