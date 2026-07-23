"""Shared pytest fixtures for WasteWise AI."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base


# A completely isolated in-memory test database.
TEST_DATABASE_URL = "sqlite://"


test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={
        "check_same_thread": False,
    },
    poolclass=StaticPool,
)


TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine,
)


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    """
    Create a clean database for every test.

    The real development or PostgreSQL database is never touched.
    """

    Base.metadata.create_all(
        bind=test_engine
    )

    session = TestingSessionLocal()

    try:
        yield session

    finally:
        session.rollback()
        session.close()

        Base.metadata.drop_all(
            bind=test_engine
        )