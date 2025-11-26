"""RaaS Core FastAPI application - Solo developer mode (no authentication)."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import requirements, organizations, projects, users, guardrails, change_requests, tasks

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("raas-core")

settings = get_settings()
logger.info("Starting RaaS Core API (solo mode - no authentication)")

# Create FastAPI app
app = FastAPI(
    title="RaaS Core API",
    description="Requirements as a Service - Solo Developer Mode",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware - Open for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all business logic routers with /api/v1 prefix
app.include_router(organizations.router, prefix="/api/v1/organizations")
app.include_router(projects.router, prefix="/api/v1/projects")
app.include_router(requirements.router, prefix="/api/v1/requirements")
app.include_router(guardrails.router, prefix="/api/v1/guardrails")
app.include_router(change_requests.router, prefix="/api/v1/change-requests")
app.include_router(users.router, prefix="/api/v1/users")
app.include_router(tasks.router, prefix="/api/v1/tasks")


@app.get("/")
def root():
    """Root endpoint with server info."""
    return {
        "name": "RaaS Core API",
        "version": "1.0.0",
        "mode": "solo",
        "authentication": False,
        "docs": "/docs",
        "description": "Requirements as a Service - Solo Developer Mode"
    }


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "mode": "solo"}
