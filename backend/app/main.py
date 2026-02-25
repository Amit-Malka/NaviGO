"""FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.chat import router as chat_router
from app.api.auth import router as auth_router
from app.config import settings

app = FastAPI(
    title="NaviGO API",
    description="AI Travel Agent powered by LangGraph + Groq Llama 4 Maverick",
    version="1.0.0",
)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(chat_router)
app.include_router(auth_router)


@app.get("/health")
async def health():
    """Health check — confirms API and LLM configuration."""
    return {
        "status": "ok",
        "llm": settings.groq_model,
        "version": "1.0.0",
    }
