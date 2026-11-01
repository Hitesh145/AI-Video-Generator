"""Check PostgreSQL connectivity and whether pgvector is enabled."""

from __future__ import annotations

from rag.database import build_engine, check_database


def main() -> int:
    engine = build_engine()
    try:
        result = check_database(engine)
        print("Database:", result["database"])
        print("pgvector version:", result["pgvector_version"])
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
