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
    LargeBinary,  # photos (profil, amis, matériel)
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


activity_friends = Table(
    "activity_friends",
    Base.metadata,
    Column("activity_id", ForeignKey("activities.id"), primary_key=True),
    Column("friend_id", ForeignKey("friends.id"), primary_key=True),
)


class Friend(Base):
    """Personne avec qui on fait certaines sorties (0.9.0). Photo en JPEG 256 px dans la base (photos.py)."""

    __tablename__ = "friends"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80), default="")
    nickname: Mapped[str] = mapped_column(String(40), default="")  # pseudo : nom affiché s'il est rempli
    note: Mapped[str] = mapped_column(Text, default="")
    photo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    has_photo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    activities: Mapped[list[Activity]] = relationship(secondary=activity_friends, back_populates="friends")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def name(self) -> str:
        """Nom affiché partout : le pseudo s'il existe, sinon prénom et nom."""
        return self.nickname or self.full_name


activity_gear = Table(
    "activity_gear",
    Base.metadata,
    Column("activity_id", ForeignKey("activities.id"), primary_key=True),
    Column("gear_id", ForeignKey("gear.id"), primary_key=True),
)

gear_default_sports = Table(
    "gear_default_sports",
    Base.metadata,
    Column("gear_id", ForeignKey("gear.id"), primary_key=True),
    Column("sport_id", ForeignKey("sports.id"), primary_key=True),
)


class Gear(Base):
    """Matériel (0.11.0) : vélo, chaussures… Au plus un matériel de chaque type par sortie (voir gear.py).
    Photo en JPEG 256 px dans la base, comme les amis."""

    __tablename__ = "gear"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10), default="bike")  # bike | shoes | other (gear.KINDS)
    brand: Mapped[str] = mapped_column(String(120), default="")  # marque et modèle
    icon: Mapped[str | None] = mapped_column(String(40), nullable=True)  # None = icône du type
    color: Mapped[str] = mapped_column(String(7), default="#2E86DE")
    since: Mapped[date | None] = mapped_column(Date, nullable=True)  # mise en service
    retired: Mapped[date | None] = mapped_column(Date, nullable=True)  # date de retrait
    max_km: Mapped[float | None] = mapped_column(Float, nullable=True)  # alerte d'usure
    price: Mapped[float | None] = mapped_column(Float, nullable=True)  # euros, pour le coût au km
    note: Mapped[str] = mapped_column(Text, default="")
    photo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    has_photo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    activities: Mapped[list[Activity]] = relationship(secondary=activity_gear, back_populates="gear")
    default_sports: Mapped[list[Sport]] = relationship(secondary=gear_default_sports)
    tasks: Mapped[list[GearTask]] = relationship(back_populates="gear", cascade="all, delete-orphan",
                                                 order_by="GearTask.name")
    services: Mapped[list[GearService]] = relationship(back_populates="gear", cascade="all, delete-orphan",
                                                       order_by="GearService.day.desc()")

    def in_service(self, day: date) -> bool:
        return (self.since is None or self.since <= day) and (self.retired is None or day <= self.retired)


class GearTask(Base):
    """Entretien récurrent d'un matériel (0.12.0) : tous les N km et/ou tous les N mois, le premier atteint."""

    __tablename__ = "gear_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    gear_id: Mapped[int] = mapped_column(ForeignKey("gear.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    every_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    every_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    gear: Mapped[Gear] = relationship(back_populates="tasks")
    services: Mapped[list[GearService]] = relationship(back_populates="task", order_by="GearService.day.desc()")


class GearService(Base):
    """Entretien fait (journal). task_id vide : entretien ponctuel, ou tâche supprimée depuis."""

    __tablename__ = "gear_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    gear_id: Mapped[int] = mapped_column(ForeignKey("gear.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("gear_tasks.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(80))  # copié de la tâche : le journal survit à sa suppression
    day: Mapped[date] = mapped_column(Date)
    km: Mapped[float | None] = mapped_column(Float, nullable=True)  # km du matériel ce jour-là
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    gear: Mapped[Gear] = relationship(back_populates="services")
    task: Mapped[GearTask | None] = relationship(back_populates="services")


class Goal(Base):
    """Objectif récurrent (0.12.0) : par ex. 1 500 km de vélo par année, 3 sorties par semaine.

    target en unité d'affichage (goals.METRICS) : km, heures, sorties ou mètres. scope : « » (tout), « fN » (famille),
    « sN » (sport), comme le filtre des sports.
    """

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    metric: Mapped[str] = mapped_column(String(12))  # distance | duration | count | elevation
    target: Mapped[float] = mapped_column(Float)
    period: Mapped[str] = mapped_column(String(6))  # week | month | year
    scope: Mapped[str] = mapped_column(String(12), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Profile(Base):
    """Ton profil (une seule ligne, id = 1). Mesures en unités usuelles : cm, kg, bpm."""

    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80), default="")
    last_name: Mapped[str] = mapped_column(String(80), default="")
    nickname: Mapped[str] = mapped_column(String(40), default="")  # affiché dans la navigation
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sex: Mapped[str] = mapped_column(String(1), default="")  # F | H | ""
    city: Mapped[str] = mapped_column(String(80), default="")
    club: Mapped[str] = mapped_column(String(120), default="")
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rest_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    photo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    has_photo: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    @property
    def display_name(self) -> str:
        return self.nickname or self.first_name or "Mon profil"


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
    route_id: Mapped[int | None] = mapped_column(ForeignKey("route_groups.id"), nullable=True, index=True)  # 0.13.0
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    sport: Mapped[Sport | None] = relationship()
    rule: Mapped[SportRule | None] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary=activity_tags, back_populates="activities", order_by="Tag.name")
    friends: Mapped[list[Friend]] = relationship(secondary=activity_friends, back_populates="activities",
                                                 order_by="Friend.first_name")
    gear: Mapped[list[Gear]] = relationship(secondary=activity_gear, back_populates="activities", order_by="Gear.kind")
    track: Mapped[ActivityTrack | None] = relationship(back_populates="activity", cascade="all, delete-orphan",
                                                       lazy="select")
    weather: Mapped[ActivityWeather | None] = relationship(back_populates="activity", cascade="all, delete-orphan")
    route: Mapped[RouteGroup | None] = relationship(back_populates="activities", foreign_keys=[route_id])

    @property
    def day(self) -> date:
        return self.start.date()

    @property
    def hr_zones(self) -> list[float | None]:
        return [self.hr_zone_1, self.hr_zone_2, self.hr_zone_3, self.hr_zone_4, self.hr_zone_5]

    @property
    def garmin_url(self) -> str:
        return f"https://connect.garmin.com/modern/activity/{self.garmin_id}"


class ActivityWeather(Base):
    """Météo au départ d'une activité (0.13.0), relevée par Garmin à la station la plus proche. Unités métriques
    (Garmin envoie des °F et des mph : conversion dans weather.py). Ligne vide = demandé, rien reçu."""

    __tablename__ = "activity_weather"

    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id"), primary_key=True)
    temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    feels_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    dew_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)  # %
    wind_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    gust_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_deg: Mapped[float | None] = mapped_column(Float, nullable=True)  # d'où vient le vent
    sky: Mapped[str] = mapped_column(String(60), default="")  # description Garmin (anglais), traduite à l'affichage
    station: Mapped[str] = mapped_column(String(40), default="")
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    activity: Mapped[Activity] = relationship(back_populates="weather")


class RouteGroup(Base):
    """Parcours fait plusieurs fois (0.13.0) : sorties au même tracé, dans le même sens (voir routes.py)."""

    __tablename__ = "route_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    custom_name: Mapped[bool] = mapped_column(Boolean, default=False)  # renommé à la main : gardé au recalcul
    rep_activity_id: Mapped[int | None] = mapped_column(ForeignKey("activities.id"), nullable=True)  # tracé de référence
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    rep: Mapped[Activity | None] = relationship(foreign_keys=[rep_activity_id])
    activities: Mapped[list[Activity]] = relationship(back_populates="route", foreign_keys="Activity.route_id",
                                                      order_by="Activity.start")


class ActivityStream(Base):
    """Données point par point d'une activité (0.14.0), téléchargées à la demande pour chronométrer les segments.

    samples_json : [[secondes depuis le départ, lat, lon, distance m, FC, altitude m], …] (FC / altitude : null
    si absentes). n = 0 : demandé, rien reçu.
    """

    __tablename__ = "activity_streams"

    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id"), primary_key=True)
    samples_json: Mapped[str] = mapped_column(Text, default="[]")
    n: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Segment(Base):
    """Portion de parcours chronométrée sur toutes les sorties qui l'empruntent dans le même sens (0.14.0)."""

    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    family_id: Mapped[int | None] = mapped_column(ForeignKey("sport_families.id"), nullable=True)
    points_json: Mapped[str] = mapped_column(Text, default="[]")  # [[lat, lon], …] dans le sens du segment
    distance_m: Mapped[float] = mapped_column(Float, default=0)
    source_activity_id: Mapped[int | None] = mapped_column(ForeignKey("activities.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    family: Mapped[SportFamily | None] = relationship()
    efforts: Mapped[list[SegmentEffort]] = relationship(back_populates="segment", cascade="all, delete-orphan",
                                                        order_by="SegmentEffort.elapsed_s")


class SegmentEffort(Base):
    """Passage d'une sortie sur un segment : le meilleur si elle l'emprunte plusieurs fois."""

    __tablename__ = "segment_efforts"
    __table_args__ = (UniqueConstraint("segment_id", "activity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id"), index=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id"), index=True)
    elapsed_s: Mapped[float] = mapped_column(Float)
    distance_m: Mapped[float] = mapped_column(Float)
    start_offset_s: Mapped[float] = mapped_column(Float, default=0)  # depuis le départ de la sortie
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    segment: Mapped[Segment] = relationship(back_populates="efforts")
    activity: Mapped[Activity] = relationship()

    @property
    def speed(self) -> float | None:
        return self.distance_m / self.elapsed_s if self.elapsed_s else None


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


class WeightEntry(Base):
    """Pesée saisie à la main (0.10.0) : une par jour, la dernière saisie du jour l'emporte."""

    __tablename__ = "weights"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    weight_kg: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


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
