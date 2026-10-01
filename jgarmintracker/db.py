from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from .classifier import reclassify
from .models import Base
from .seed import seed
from .upgrades import run_upgrades

SessionLocal = sessionmaker(expire_on_commit=False)

# Colonnes ajoutées après la création d'une table : {table: {colonne: définition SQL}}.
# create_all ne modifie pas une table existante ; on les ajoute ici au démarrage.
NEW_COLUMNS: dict[str, dict[str, str]] = {
    "activities": {  # 0.2.0 : détails supplémentaires d'une activité
        **{name: "FLOAT" for name in (
            "max_speed", "elevation_loss_m", "min_elevation_m", "max_elevation_m", "elapsed_s",
            "hr_zone_1", "hr_zone_2", "hr_zone_3", "hr_zone_4", "hr_zone_5", "cadence_avg", "cadence_max",
            "stride_cm", "fastest_1k_s", "fastest_mile_s", "fastest_5k_s", "fastest_40k_s", "water_ml", "vo2max",
        )},
        "lap_count": "INTEGER",
        "steps": "INTEGER",
        "is_pr": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "sync_runs": {"tracks_added": "INTEGER NOT NULL DEFAULT 0"},  # 0.3.0
}


def default_db_path() -> Path:
    return Path(os.environ.get("JGARMIN_DB") or Path.cwd() / "jgarmin.db")


def init_db(path: str | Path | None = None) -> Path:
    """Ouvre (ou crée) la base SQLite et y place les sports de départ si elle est vide."""
    p = Path(path) if path else default_db_path()
    engine = create_engine(f"sqlite:///{p}", connect_args={"timeout": 30})
    SessionLocal.configure(bind=engine)
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    with SessionLocal() as s:
        seeded = seed(s)
        if run_upgrades(s) or seeded:
            reclassify(s)
        s.commit()
    return p


def _add_missing_columns(engine) -> None:
    insp = inspect(engine)
    with engine.begin() as con:
        for table, columns in NEW_COLUMNS.items():
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    con.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def new_session() -> Session:
    return SessionLocal()
