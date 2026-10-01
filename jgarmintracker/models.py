from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Unité d'allure d'un sport : détermine l'affichage (min/km, km/h, min/100 m) et le graphique de progression.
PACE_UNITS = {
    "min_km": "allure (min/km)",
    "kmh": "vitesse (km/h)",
    "min_100m": "allure (min/100 m)",
    "none": "aucune",
}


class AppliedUpgrade(Base):
    """Mises à jour de données déjà appliquées (voir upgrades.py) : chacune ne tourne qu'une fois."""

    __tablename__ = "applied_upgrades"

    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Setting(Base):
    """Réglages de l'interface et de la synchro (0.4.0) : une valeur JSON par nom. Voir settings.py."""

    __tablename__ = "settings"

    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="null")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class SportFamily(Base):
    __tablename__ = "sport_families"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    icon: Mapped[str | None] = mapped_column(String(40), nullable=True)  # nom Phosphor (voir icons.py)

    sports: Mapped[list[Sport]] = relationship(back_populates="family", order_by="(Sport.position, Sport.name)")


class Sport(Base):
    __tablename__ = "sports"
    __table_args__ = (UniqueConstraint("family_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("sport_families.id"))
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(String(7), default="#8A94A0")
    pace_unit: Mapped[str] = mapped_column(String(10), default="none")
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Sport attribué quand aucune règle ne s'applique (un seul : « Autre »).
    fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    icon: Mapped[str | None] = mapped_column(String(40), nullable=True)  # None = icône de la famille

    family: Mapped[SportFamily] = relationship(back_populates="sports")

    @property
    def icon_name(self) -> str:
        """Icône affichée : celle du sport, sinon celle de sa famille, sinon une icône générique."""
        return self.icon or self.family.icon or "pulse"

    @property
    def label(self) -> str:
        return self.name if self.name == self.family.name else f"{self.family.name} › {self.name}"


class SportRule(Base):
    __tablename__ = "sport_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    field: Mapped[str] = mapped_column(String(20))  # type_key | name
    match_type: Mapped[str] = mapped_column(String(20))  # equals | contains | regex
    pattern: Mapped[str] = mapped_column(String(255))
    sport_id: Mapped[int] = mapped_column(ForeignKey("sports.id"))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    origin: Mapped[str] = mapped_column(String(10), default="manual")  # seed | learned | manual
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    sport: Mapped[Sport] = relationship()


activity_tags = Table(
    "activity_tags",
    Base.metadata,
    Column("activity_id", ForeignKey("activities.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
)


class Tag(Base):
    """Étiquette libre posée à la main : « Marathon », « Vacances »…"""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)

    activities: Mapped[list[Activity]] = relationship(secondary=activity_tags, back_populates="tags")


class Activity(Base):
    """Une activité Garmin. Unités SI : secondes, mètres, m/s."""

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    garmin_id: Mapped[int] = mapped_column(Integer, unique=True)
    start: Mapped[datetime] = mapped_column(DateTime, index=True)  # heure locale de l'activité
    type_key: Mapped[str] = mapped_column(String(60), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    sport_id: Mapped[int | None] = mapped_column(ForeignKey("sports.id"), nullable=True, index=True)
    sport_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    # rule | manual | fallback
    sport_source: Mapped[str] = mapped_column(String(10), default="fallback")
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("sport_rules.id"), nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    moving_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_speed: Mapped[float | None] = mapped_column(Float, nullable=True)  # m/s
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    aerobic_te: Mapped[float | None] = mapped_column(Float, nullable=True)
    anaerobic_te: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Ajoutés en 0.2.0 (voir db.NEW_COLUMNS et upgrades.py) : lus dans le même JSON de la liste d'activités.
    max_speed: Mapped[float | None] = mapped_column(Float, nullable=True)  # m/s
    elevation_loss_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    elapsed_s: Mapped[float | None] = mapped_column(Float, nullable=True)  # pauses comprises
    lap_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hr_zone_1: Mapped[float | None] = mapped_column(Float, nullable=True)  # secondes dans la zone
    hr_zone_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    hr_zone_3: Mapped[float | None] = mapped_column(Float, nullable=True)
    hr_zone_4: Mapped[float | None] = mapped_column(Float, nullable=True)
    hr_zone_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    cadence_avg: Mapped[float | None] = mapped_column(Float, nullable=True)  # pas/min (course)
    cadence_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    stride_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fastest_1k_s: Mapped[float | None] = mapped_column(Float, nullable=True)  # meilleur km dans la sortie
    fastest_mile_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    fastest_5k_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    fastest_40k_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_ml: Mapped[float | None] = mapped_column(Float, nullable=True)
    vo2max: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_pr: Mapped[bool] = mapped_column(Boolean, default=False)  # record personnel selon Garmin
    # 0.7.0 : vérifications. Une activité exclue reste dans la liste mais sort de toutes les statistiques.
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    exclude_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ignore_max_speed: Mapped[bool] = mapped_column(Boolean, default=False)  # pointe GPS aberrante
    review_ok: Mapped[bool] = mapped_column(Boolean, default=False)  # « c'est bien moi » : plus d'alerte
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    sport: Mapped[Sport | None] = relationship()
    rule: Mapped[SportRule | None] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary=activity_tags, back_populates="activities", order_by="Tag.name")
    track: Mapped[ActivityTrack | None] = relationship(back_populates="activity", cascade="all, delete-orphan",
                                                       lazy="select")

    @property
    def day(self) -> date:
        return self.start.date()

    @property
    def hr_zones(self) -> list[float | None]:
        return [self.hr_zone_1, self.hr_zone_2, self.hr_zone_3, self.hr_zone_4, self.hr_zone_5]

    @property
    def garmin_url(self) -> str:
        return f"https://connect.garmin.com/modern/activity/{self.garmin_id}"


class ActivityTrack(Base):
    """Tracé GPS simplifié d'une activité (0.3.0). Table à part : la liste des activités reste légère.

    Une ligne sans points (n_points = 0) signifie « demandé, pas de tracé » (activité en salle) : pas de nouvelle demande.
    """

    __tablename__ = "activity_tracks"

    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id"), primary_key=True)
    points_json: Mapped[str] = mapped_column(Text, default="[]")  # [[lat, lon], …] arrondis à 5 décimales (~1 m)
    n_points: Mapped[int] = mapped_column(Integer, default=0)
    preview_path: Mapped[str] = mapped_column(Text, default="")  # chemin SVG de la mini-carte
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    activity: Mapped[Activity] = relationship(back_populates="track")


class DailyHealth(Base):
    """Une ligne par jour. La nuit de sommeil est rattachée au jour du réveil."""

    __tablename__ = "daily_health"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    resting_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deep_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    light_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rem_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awake_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_charged: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_drained: Mapped[int | None] = mapped_column(Integer, nullable=True)
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stress_avg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stress_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vo2max: Mapped[float | None] = mapped_column(Float, nullable=True)
    # JSON brut par source, pour recalculer sans tout re-télécharger.
    raw_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # FC repos, Body Battery, pas, stress
    raw_sleep: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_vo2max: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    mode: Mapped[str] = mapped_column(String(12), default="incremental")  # incremental | full
    activities_added: Mapped[int] = mapped_column(Integer, default=0)
    activities_updated: Mapped[int] = mapped_column(Integer, default=0)
    days_added: Mapped[int] = mapped_column(Integer, default=0)
    days_updated: Mapped[int] = mapped_column(Integer, default=0)
    tracks_added: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="running")  # running | ok | error
    message: Mapped[str] = mapped_column(Text, default="")
