"""Create a new, empty SQLite database using the application's full schema."""

import argparse
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "macro_predictor_fresh.db",
        help="destination database path (must not already exist)",
    )
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error(f"refusing to overwrite existing database: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    os.environ["MACRO_PREDICTOR_DATABASE_URL"] = f"sqlite:///{output.as_posix()}"

    from database import Base, SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        nonempty = []
        for table in Base.metadata.sorted_tables:
            if db.execute(table.select().limit(1)).first() is not None:
                nonempty.append(table.name)
        if nonempty:
            raise RuntimeError(
                "Fresh schema unexpectedly contains rows in: " + ", ".join(nonempty)
            )
    finally:
        db.close()
    print(f"Created empty database: {output}")
    print(f"Tables created: {len(Base.metadata.tables)}")
    print("Rows: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
