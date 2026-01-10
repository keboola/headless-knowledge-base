"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from knowledge_base.api.health import router as health_router
from knowledge_base.api.search import router as search_router
from knowledge_base.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    description="AI-powered knowledge base with semantic search and RAG capabilities",
    version="0.1.0",
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for now, restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(search_router)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint with basic application info."""
    return {
        "name": settings.APP_NAME,
        "version": "0.1.0",
        "docs": "/docs",
        "streamlit_ui": "Run: streamlit run src/knowledge_base/web/streamlit_app.py",
    }
