import os
import sys
import time
from pathlib import Path

# Add project root (for core.*) and api/ (for deps.py) to sys.path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "api"))
sys.path.insert(0, str(_root))

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

from api.routes import webhooks, channels, chat, reminders, documents, auth as auth_routes, notifications, adherence, family as family_routes, sessions  # noqa: E402
from core.supabase_client import init_supabase_client, close_supabase_client
from core.storage import ensure_bucket_exists
from core.scheduler import start_scheduler, stop_scheduler

app = FastAPI(
    title="MedAI API",
    description="API para el agente AI de apoyo para la adherencia a tratamientos médicos",
    version="1.0.0",
)

cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await init_supabase_client()
    print("✅ Supabase client initialized")
    try:
        await ensure_bucket_exists()
        print("✅ Supabase Storage bucket ready")
    except Exception as e:
        print(f"⚠️  Supabase Storage not reachable: {e}")
    start_scheduler()
    print("✅ Reminder scheduler started")


@app.on_event("shutdown")
async def shutdown():
    stop_scheduler()
    await close_supabase_client()
    print("✅ Supabase client closed")


class RequestTimeMiddleware:
    """Pure ASGI middleware — only injects X-Request-Time for HTTP, leaves WebSocket untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()

        async def send_with_timing(message):
            if message["type"] == "http.response.start":
                duration = time.perf_counter() - start
                headers = list(message.get("headers", []))
                headers.append((b"x-request-time", f"{duration:.4f}s".encode()))
                await send({**message, "headers": headers})
            else:
                await send(message)

        await self.app(scope, receive, send_with_timing)


app.add_middleware(RequestTimeMiddleware)


@app.get("/health", tags=["Meta"])
def health():
    return {
        "status": "ok",
        "provider": os.getenv("LLM_PROVIDER", "ollama"),
        "supabase": os.getenv("SUPABASE_URL", "not configured")
    }


# Incluir routers
app.include_router(webhooks.router)
app.include_router(channels.router, prefix="/api", tags=["Channels"])
app.include_router(chat.router)
app.include_router(reminders.router, prefix="/api", tags=["Reminders"])
app.include_router(documents.router, prefix="/api", tags=["Documents"])
app.include_router(auth_routes.router, prefix="/api", tags=["Auth"])
app.include_router(notifications.router, prefix="/api", tags=["Notifications"])
app.include_router(adherence.router, prefix="/api", tags=["Adherence"])
app.include_router(family_routes.router, prefix="/api", tags=["Family"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions"])
