"""TOML settings; credentials are never part of serializable settings."""

import os
import tomllib
from pathlib import Path
from dotenv import dotenv_values
from brandprobe.schemas import AuditConfig


def load_config(path: Path) -> AuditConfig:
    return AuditConfig.model_validate(tomllib.loads(path.read_text()))


def api_key(root: Path, name: str = "OPENROUTER_API_KEY") -> str:
    values = {
        **dotenv_values(root / ".env"),
        **dotenv_values(root / ".env.local"),
        **os.environ,
    }
    return values.get(name) or ""
