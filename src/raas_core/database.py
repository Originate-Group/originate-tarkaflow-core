"""Database connection and session management."""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from .config import get_settings

settings = get_settings()

# Create database engine
# Conservative pool settings for Supabase Session mode (max ~15-20 connections)
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,          # Verify connections before using
    pool_size=3,                 # Base pool of 3 connections
    max_overflow=7,              # Allow up to 10 total connections
    pool_recycle=3600,           # Recycle connections every hour
    pool_timeout=30,             # Timeout after 30 seconds
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency function to get database session.

    Yields:
        Session: SQLAlchemy database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
