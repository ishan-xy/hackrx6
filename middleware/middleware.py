import os
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

@app.middleware("http")
async def authentication_middleware(request: Request, call_next):
    authorization = request.headers.get("authorization")
    if authorization is None:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Authorization header is missing"}
        )
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid authentication scheme"}
            )
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid Authorization header format. Must be 'Bearer <token>'."}
        )
    if token != os.getenv("TOKEN"):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "detail": "Invalid authentication credentials"
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    response = await call_next(request)
    return response
