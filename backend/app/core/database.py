from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args={
        "connect_timeout": 5,
        # Evita fallos GSSAPI/Kerberos en macOS con Postgres local (Docker)
        "gssencmode": "disable",
        "sslmode": "disable",
    },
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection() -> None:
    """Verifica conectividad al arrancar y calienta el pool de conexiones."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
