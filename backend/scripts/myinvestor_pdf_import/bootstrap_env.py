"""Carga .env / .env.server igual que app.core.config y run.sh (APP_PROFILE)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _read_profile_from_argv(argv: list[str]) -> str | None:
    for index, arg in enumerate(argv):
        if arg in ("--profile", "-p") and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--profile="):
            return arg.split("=", 1)[1]
    return None


def normalize_app_profile(raw: str) -> str:
    """local → .env ; server/pre → .env.server (PostgreSQL pre)."""
    value = raw.strip().lower()
    if value in ("server", "pre"):
        return "server"
    if value in ("local", ""):
        return "local"
    return value


def env_file_for_profile(app_profile: str) -> Path:
    name = ".env.server" if app_profile == "server" else ".env"
    return BACKEND_ROOT / name


def bootstrap_backend_env(argv: list[str] | None = None) -> tuple[str, Path]:
    """Define APP_PROFILE, carga dotenv y devuelve (profile, ruta env)."""
    from dotenv import load_dotenv

    argv = argv if argv is not None else sys.argv
    cli_profile = _read_profile_from_argv(argv)
    raw = cli_profile if cli_profile is not None else os.environ.get("APP_PROFILE", "local")
    app_profile = normalize_app_profile(raw)
    os.environ["APP_PROFILE"] = app_profile

    env_path = env_file_for_profile(app_profile)
    if not env_path.is_file():
        raise SystemExit(
            f"No existe {env_path.name} en {BACKEND_ROOT}. "
            f"Perfil APP_PROFILE={app_profile!r}."
        )
    load_dotenv(dotenv_path=env_path, override=True)
    return app_profile, env_path
