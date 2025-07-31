from typing import Union
from fastapi import FastAPI
from pydantic import BaseModel
from handlers.hackrx import router
from middleware.middleware import authentication_middleware
from middleware.logMiddleware import discord_webhook_middleware
from starlette.middleware.base import BaseHTTPMiddleware

app = FastAPI()
app.include_router(router)
app.add_middleware(BaseHTTPMiddleware, dispatch=discord_webhook_middleware)
app.add_middleware(BaseHTTPMiddleware, dispatch=authentication_middleware)

@app.get("/")
def read_root():
    return {"message": "Welcome to the HackRX API"}
tags=["hackrx"]