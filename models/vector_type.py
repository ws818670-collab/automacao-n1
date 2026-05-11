"""
VectorType: armazena vetores de floats como JSON (TEXT) no banco.
Funciona nativamente com SQLite e PostgreSQL sem extensões de servidor.
"""

from __future__ import annotations

import json

from sqlalchemy.types import Text, TypeDecorator


class VectorType(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.dim = dim

    def process_bind_param(self, value: object, dialect: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value)

    def process_result_value(self, value: object, dialect: object) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return value
        return json.loads(value)
