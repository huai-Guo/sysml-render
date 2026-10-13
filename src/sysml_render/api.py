from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .svg import RenderRequest, render_svg


@asynccontextmanager
async def lifespan(app):
    token = os.getenv("SYSML_RENDER_SERVICE_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("SYSML_RENDER_SERVICE_TOKEN must contain at least 32 characters")
    app.state.token = token
    yield


app = FastAPI(title="SysML semantic image service", lifespan=lifespan, docs_url=None, redoc_url=None)


async def authorized(request: Request, authorization: str = Header(default="")):
    if not secrets.compare_digest(authorization, "Bearer " + request.app.state.token):
        raise HTTPException(401, "Service authentication required")


@app.middleware("http")
async def bounded_body(request: Request, call_next):
    # Consume bounded chunks before JSON parsing; Content-Length alone is insufficient.
    body = bytearray()
    try:
        async with asyncio.timeout(10):
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 4 * 1024 * 1024:
                    return JSONResponse({"detail": "Request too large"}, status_code=413)
    except TimeoutError:
        return JSONResponse({"detail": "Request timed out"}, status_code=408)
    request._body = bytes(body)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.post("/v1/render", dependencies=[Depends(authorized)])
def render(request: RenderRequest):
    try:
        return render_svg(request)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
