import os
import sys
import hashlib
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set, Callable
from contextlib import contextmanager
import json

import pandas as pd
import numpy as np

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Date, DateTime,
    ForeignKey, Index, UniqueConstraint, event, text, DECIMAL, CheckConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from sqlalchemy.dialects.mysql import insert as mysql_insert
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    db_host: str = Field(default="localhost")
    db_port: int = Field(default=3306)
    db_user: str = Field(default="etl_user")
    db_password: str = Field(default="")
    db_name: str = Field(default="sfe_dwh")
    db_pool_size: int = Field(default=10)

    data_folder: Path = Field(default=Path("./data_source"))
    batch_size: int = Field(default=500)
    max_retries: int = Field(default=3)

    log_level: str = Field(default="INFO")
    log_file: Optional[Path] = Field(default=None)

    hash_algorithm: str = Field(default="sha256", alias="HASH_ALGO")

    testing_mode: bool = Field(default=False)

    @field_validator("db_password")
    @classmethod
    def password_not_empty(cls, v: str, info) -> str:
        if info.data.get("testing_mode", False):
            return v
        if not v:
            raise ValueError(
                "ERREUR: DB_PASSWORD est vide!\n"
                "Crée un fichier .env à la racine avec:\n"
                "DB_PASSWORD=TonMotDePasse"
            )
        if len(v) < 8:
            raise ValueError("Le mot de passe doit contenir au moins 8 caractères")
        return v

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

# ============================================================
# LOGGING STRUCTURÉ JSON
# ============================================================

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if hasattr(record, "etl_context"):
            log_obj["context"] = record.etl_context
        return json.dumps(log_obj, ensure_ascii=False, default=str)


def setup_logging(settings: Settings) -> logging.Logger:
    logger = logging.getLogger("ETL_SFE_v3")
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    logger.handlers = []

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    logger.addHandler(ch)

    if settings.log_file:
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(settings.log_file, encoding="utf-8")
        fh.setFormatter(JSONFormatter())
        logger.addHandler(fh)

    return logger


# ============================================================
# MODÈLES SQLAlchemy ORM
# ============================================================

Base = declarative_base()

class Entite(Base):
    __tablename__ = "dim_entites"
    id_entite = Column("id_entite", Integer, primary_key=True)
    code_entite = Column(String(50), unique=True, nullable=False, index=True)
    nom_entite = Column(String(255), nullable=False)
    date_creation = Column(DateTime, default=datetime.utcnow)
    actions = relationship("ActionFact", back_populates="entite")

class Responsable(Base):
    __tablename__ = "dim_responsables"
    id_responsable = Column("id_responsable", Integer, primary_key=True)
    nom_complet = Column(String(255), unique=True, nullable=False)
    email = Column(String(255))
    service = Column(String(100))
    actions = relationship("ActionFact", back_populates="responsable")

class Statut(Base):
    __tablename__ = "dim_statuts"
    id_statut = Column("id_statut", Integer, primary_key=True)
    code_statut = Column(String(50), unique=True, nullable=False)
    libelle = Column(String(100), nullable=False)
    ordre_avancement = Column(DECIMAL(3, 2), default=0.0)
    actions = relationship("ActionFact", back_populates="statut")

class Priorite(Base):
    __tablename__ = "dim_priorites"
    id_priorite = Column("id_priorite", Integer, primary_key=True)
    code_priorite = Column(String(50), unique=True, nullable=False)
    libelle = Column(String(100), nullable=False)
    ordre = Column(Integer, default=0)
    actions = relationship("ActionFact", back_populates="priorite")

class SourceType(Base):
    __tablename__ = "dim_source_types"
    id_source_type = Column("id_source_type", Integer, primary_key=True)
    code_source = Column(String(50), unique=True, nullable=False)
    libelle = Column(String(255))
    actions = relationship("ActionFact", back_populates="source_type")

class DateDim(Base):
    __tablename__ = "dim_dates"
    id_date = Column("id_date", Integer, primary_key=True)
    date_full = Column(Date, unique=True, nullable=False)
    annee = Column(Integer, nullable=False)
    trimestre = Column(Integer, nullable=False)
    mois_num = Column(Integer, nullable=False)
    mois_nom = Column(String(20), nullable=False)
    semaine_annee = Column(Integer, nullable=False)
    jour_semaine = Column(Integer, nullable=False)
    jour_nom = Column(String(20), nullable=False)
    est_weekend = Column(Integer, nullable=False)
    est_jour_ferie = Column(Integer, default=0)

class ActionFact(Base):
    __tablename__ = "fact_actions"

    id_action = Column(Integer, primary_key=True)
    action_key = Column(String(64), nullable=False, index=True)

    id_entite = Column(Integer, ForeignKey("dim_entites.id_entite"), nullable=False)
    id_responsable = Column(Integer, ForeignKey("dim_responsables.id_responsable"), nullable=False)
    id_statut = Column(Integer, ForeignKey("dim_statuts.id_statut"), nullable=False)
    id_priorite = Column(Integer, ForeignKey("dim_priorites.id_priorite"), nullable=False)
    id_source_type = Column(Integer, ForeignKey("dim_source_types.id_source_type"), nullable=False)
    id_date_echeance = Column(Integer, ForeignKey("dim_dates.id_date"))
    id_date_realisation = Column(Integer, ForeignKey("dim_dates.id_date"))

    description_action = Column(Text, nullable=False)
    localisation = Column(String(500))
    constat_original = Column(Text)
    recommandation = Column(Text)

    fichier_source = Column(String(255))
    sheet_source = Column(String(100))
    ligne_source = Column(Integer)

    date_echeance = Column(Date)
    date_realisation = Column(Date)

    date_debut_validite = Column(DateTime, default=datetime.utcnow, nullable=False)
    date_fin_validite = Column(DateTime, nullable=True)
    est_actif = Column(Integer, default=1, nullable=False)

    date_import = Column(DateTime, default=datetime.utcnow)
    import_batch_id = Column(String(36), index=True)

    entite = relationship("Entite", back_populates="actions")
    responsable = relationship("Responsable", back_populates="actions")
    statut = relationship("Statut", back_populates="actions")
    priorite = relationship("Priorite", back_populates="actions")
    source_type = relationship("SourceType", back_populates="actions")

    __table_args__ = (
        Index("idx_action_active", "action_key", "est_actif"),
        Index("idx_batch", "import_batch_id"),
        CheckConstraint("est_actif IN (0, 1)", name="chk_est_actif"),
    )


# ============================================================
# DATA QUALITY FRAMEWORK
# ============================================================

class QualityRule(ABC):
    @abstractmethod
    def validate(self, record: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        pass

class NotEmptyRule(QualityRule):
    def __init__(self, field: str):
        self.field = field

    def validate(self, record: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        val = record.get(self.field)
        if not val or str(val).strip().lower() in ["nan", "none", "", "na", "non défini"]:
            return False, f"Champ '{self.field}' vide"
        return True, None

class DateFormatRule(QualityRule):
    def __init__(self, field: str, allow_serial: bool = True):
        self.field = field
        self.allow_serial = allow_serial

    def validate(self, record: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        val = record.get(self.field)
        if val is None:
            return True, None
        val_str = str(val).strip().lower()
        if val_str in ["", "na", "non défini", "en continu", "selon pmp",
                       "prochain arrêt chaud", "prochain arrêt froid"]:
            return True, None
        parsed = DateParser.parse(val, allow_serial=self.allow_serial)
        if parsed is None and val is not None:
            return True, f"WARNING: Date '{val}' non parsable, sera NULL en base"
        return True, None

class PriorityConsistencyRule(QualityRule):
    def validate(self, record: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        priorite = str(record.get("priorite", "")).lower()
        statut = str(record.get("statut", "")).lower()
        if "critique" in priorite and statut in ["non fait", "planifié"]:
            return True, f"WARNING: Action critique avec statut '{statut}'"
        return True, None


class DataQualityEngine:
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.rules: List[QualityRule] = []
        self.issues: List[Dict] = []

    def add_rule(self, rule: QualityRule) -> "DataQualityEngine":
        self.rules.append(rule)
        return self

    def validate(self, record: Dict[str, Any], context: str = "") -> Tuple[bool, List[str]]:
        errors = []
        warnings = []
        for rule in self.rules:
            is_valid, message = rule.validate(record)
            if not is_valid:
                if message and message.startswith("WARNING:"):
                    warnings.append(message)
                else:
                    errors.append(message)
        if errors:
            self.issues.append({
                "context": context,
                "record": str(record.get("description", "N/A"))[:100],
                "errors": errors,
                "warnings": warnings
            })
            return False, errors
        return True, warnings

    def get_report(self) -> Dict[str, Any]:
        return {
            "total_rules": len(self.rules),
            "total_issues": len(self.issues),
            "issues_by_type": self._categorize_issues(),
            "sample_issues": self.issues[:10]
        }

    def _categorize_issues(self) -> Dict[str, int]:
        categories = {}
        for issue in self.issues:
            for err in issue["errors"]:
                cat = err.split(":")[0] if ":" in err else "OTHER"
                categories[cat] = categories.get(cat, 0) + 1
        return categories


# ============================================================
# UTILITAIRES
# ============================================================

class DateParser:
    EXCEL_EPOCH = datetime(1899, 12, 30)

    @classmethod
    def parse(cls, value: Any, allow_serial: bool = True) -> Optional[date]:
        if pd.isna(value) or value is None:
            return None

        s = str(value).strip().lower()
        if s in ["nan", "none", "", "na", "non défini", "en continu"]:
            return None

        if allow_serial and s.replace(".", "").isdigit() and float(s) > 30000:
            try:
                return (cls.EXCEL_EPOCH + pd.Timedelta(days=int(float(s)))).date()
            except Exception:
                pass

        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d",
                    "%d/%m/%y", "%m/%d/%Y", "%d.%m.%Y"]:
            try:
                return datetime.strptime(s[:10], fmt).date()
            except ValueError:
                continue

        try:
            return pd.to_datetime(value).date()
        except Exception:
            pass

        return None


class HashGenerator:
    def __init__(self, algorithm: str = "sha256"):
        self.algorithm = algorithm

    def generate(self, action: str, responsable: str, entite: str,
                 source: str, date_ech: Optional[date] = None) -> str:
        components = [
            action.strip().lower(),
            responsable.strip().lower(),
            entite.strip().lower(),
            source.strip().lower(),
            str(date_ech) if date_ech else "no_date"
        ]
        combined = "|".join(components)

        if self.algorithm == "sha256":
            return hashlib.sha256(combined.encode("utf-8")).hexdigest()
        elif self.algorithm == "md5":
            return hashlib.md5(combined.encode("utf-8")).hexdigest()
        else:
            raise ValueError(f"Algorithme non supporté: {self.algorithm}")


class SmartColumnDetector:
    """
    Détecteur intelligent de colonnes — fonctionne avec n'importe quel fichier
    sans avoir besoin de connaître les noms de colonnes à l'avance.
    Utilise le fuzzy matching + détection sémantique.
    """

    SEMANTIC_MAP = {
        "action": [
            "actions de remise en état", "actions de remise en etat",
            "action", "remise en état", "remise en etat", "recommandation",
            "mesure", "tâche", "tache", "travail", "intervention", "correction",
            "amélioration", "amelioration", "activité", "activite", "description",
            "observations"
        ],
        "statut": [
            "statut fait / non fait", "statut\n fait / non fait",
            "statut", "état", "etat", "avancement", "progression", "fait",
            "done", "status"
        ],
        "responsable": [
            "responsable", "owner", "pilote", "fait par", "charge", "assigné",
            "assigne", "gestionnaire", "porteur", "interlocuteur", "réalisé par"
        ],
        "entite": [
            "entité", "entite", "site", "unité", "unite", "secteur", "département",
            "departement", "atelier", "usine", "zone", "périmètre", "perimetre"
        ],
        "priorite": [
            "priorité", "priorite", "criticité", "criticite", "urgence",
            "gravité", "gravite", "sévérité", "severite", "niveau", "importance"
        ],
        "date_echeance": [
            "deadline", "délai", "delai", "date fin", "date de fin", "échéance",
            "echeance", "due date", "fin prévue", "fin prevue", "date limite"
        ],
        "date_debut": [
            "date début", "date debut", "date de début", "date de debut",
            "start", "début", "debut", "date", "ouverture"
        ],
        "localisation": [
            "localisation", "local", "emplacement", "lieu", "position",
            "equipement", "équipement", "installation", "ligne", "unité"
        ],
        "constat": [
            "constat", "observation", "remarque", "problème", "probleme",
            "anomalie", "défaut", "defaut", "écart", "ecart", "non-conformité"
        ],
    }

    @classmethod
    def detect_columns(cls, df: pd.DataFrame) -> Dict[str, Optional[str]]:
        """
        Retourne un dict {role: nom_colonne} pour toutes les colonnes détectées.
        Exemple: {"action": "Actions de remise en état", "statut": "Statut\nFait/Non Fait", ...}
        """
        col_normalized = {}
        for col in df.columns:
            normalized = str(col).strip().lower()
            normalized = normalized.replace("\n", " ").replace("\r", " ")
            normalized = " ".join(normalized.split())  
            col_normalized[col] = normalized

        result = {role: None for role in cls.SEMANTIC_MAP}
        scores = {role: {} for role in cls.SEMANTIC_MAP}

        for col, col_norm in col_normalized.items():
            for role, keywords in cls.SEMANTIC_MAP.items():
                score = cls._score(col_norm, keywords)
                if score > 0:
                    scores[role][col] = score

        for role in cls.SEMANTIC_MAP:
            if scores[role]:
                best_col = max(scores[role], key=scores[role].get)
                if scores[role][best_col] >= 1:
                    result[role] = best_col

        return result

    @classmethod
    def _score(cls, col_norm: str, keywords: List[str]) -> float:
        score = 0.0
        for kw in keywords:
            kw_norm = kw.lower()
            if kw_norm == col_norm:
                score += 3.0  
            elif kw_norm in col_norm:
                score += 2.0 
            elif col_norm in kw_norm:
                score += 1.0  
            else:
                col_words = set(col_norm.split())
                kw_words = set(kw_norm.split())
                common = col_words & kw_words
                if common:
                    score += len(common) * 0.5
        return score
    MAPPING = {
        "psm": "PSM",
        "nh3": "NH3", "ammoniac": "NH3",
        "haute_tension": "HT", "haute tension": "HT",
        "fire_fighting": "FF", "fighting": "FF", "feu": "FF", "fire": "FF",
        "audit": "Audit", "recommandation": "Audit",
        "diagnostic": "Diagnostic",
        "ht": "HT",
        "ff": "FF",
    }

    @classmethod
    def detect(cls, filename: str) -> str:
        n = filename.lower()
        for key, value in cls.MAPPING.items():
            if key in n:
                return value
        return "Autre"


# ============================================================
# AMÉLIORATION 2: Clé PK centralisée — fini la duplication DRY
# ============================================================

_MODEL_PK_MAP: Dict[str, str] = {
    "Entite":       "id_entite",
    "Responsable":  "id_responsable",
    "Statut":       "id_statut",
    "Priorite":     "id_priorite",
    "SourceType":   "id_source_type",
    "DateDim":      "id_date",
}

# ============================================================
# PARSERS STRATÉGIQUES
# ============================================================

class SourceTypeDetector:
    MAPPING = {
        "psm": "PSM",
        "nh3": "NH3", "ammoniac": "NH3",
        "haute_tension": "HT", "haute tension": "HT",
        "fire_fighting": "FF", "fighting": "FF", "feu": "FF", "fire": "FF",
        "audit": "Audit", "recommandation": "Audit",
        "diagnostic": "Diagnostic",
        "ht": "HT",
        "ff": "FF",
    }

    @classmethod
    def detect(cls, filename: str) -> str:
        n = filename.lower()
        for key in sorted(cls.MAPPING.keys(), key=len, reverse=True):
            if key in n:
                return cls.MAPPING[key]
        return "Autre"


class FileParser(ABC):
    @abstractmethod
    def can_parse(self, df: pd.DataFrame, filename: str, sheet: str) -> bool:
        pass

    @abstractmethod
    def parse(self, df: pd.DataFrame, filename: str, sheet: str) -> List[Dict[str, Any]]:
        pass

    def _extract_field(self, row: pd.Series, candidates: List[str]) -> Optional[str]:
        """Méthode utilitaire commune à tous les parsers — évite la duplication."""
        for col in row.index:
            col_clean = str(col).strip().lower()
            for cand in candidates:
                if cand in col_clean:
                    val = row[col]
                    if pd.notna(val) and str(val).strip():
                        return str(val).strip()
        return None


class PSMParser(FileParser):
    def can_parse(self, df: pd.DataFrame, filename: str, sheet: str) -> bool:
        return "psm" in filename.lower()

    def parse(self, df: pd.DataFrame, filename: str, sheet: str) -> List[Dict[str, Any]]:
        if len(df) < 2:
            return []

        header_row = df.iloc[0]
        df = df.iloc[1:].copy()
        df.columns = [str(c).strip().lower() if pd.notna(c) else f"col_{i}"
                      for i, c in enumerate(header_row)]

        records = []
        for idx, row in df.iterrows():
            action = self._extract_field(row, ["action", "actions"])
            if not action:
                continue

            entite = self._extract_field(row, ["entité", "entite", "site", "unité"]) or "JFC1"

            records.append({
                "description": action,
                "statut": self._extract_field(row, ["statut", "avancement"]),
                "responsable": self._extract_field(row, ["owner", "responsable", "pilote"]),
                "entite": entite,
                "priorite": self._extract_field(row, ["priorité", "priorite"]),
                "date_echeance": self._extract_field(row, ["date de fin", "date fin"]),
                "date_debut": self._extract_field(row, ["date de début", "date début"]),
                "source_detail": f"{filename} ({sheet})",
                "ligne_source": idx
            })
        return records


class RecommandationsParser(FileParser):
    def can_parse(self, df: pd.DataFrame, filename: str, sheet: str) -> bool:
        fname = filename.lower()
        if "ht" in fname or "haute tension" in fname:
            return False
        return "recommandation" in fname or "audit" in fname

    def parse(self, df: pd.DataFrame, filename: str, sheet: str) -> List[Dict[str, Any]]:
        records = []
        col_mapping = {
            "description": ["description du résultat de l'audit", "constat", "description"],
            "recommandation": ["recommandations du site suite au diagnostic ff n2", "recommandation"],
            "localisation": ["localisation du constat", "localisation"],
            "entite": ["concernés", "entité", "entite"],
            "statut": ["avancement"],
            "delai": ["délai", "delai"]
        }

        for idx, row in df.iterrows():
            rec = self._extract_field(row, col_mapping["recommandation"])
            if not rec:
                continue

            records.append({
                "description": rec,
                "constat_original": self._extract_field(row, col_mapping["description"]),
                "localisation": self._extract_field(row, col_mapping["localisation"]),
                "statut": self._extract_field(row, col_mapping["statut"]) or "Non défini",
                "responsable": "Non assigné",
                "entite": self._extract_field(row, col_mapping["entite"]) or "Général",
                "priorite": self._infer_priorite(row),
                "date_echeance": self._extract_field(row, col_mapping["delai"]),
                "source_detail": f"{filename} ({sheet})",
                "ligne_source": idx
            })
        return records

    def _infer_priorite(self, row: pd.Series) -> str:
        desc = str(row.get("description du résultat de l'audit", "")).lower()
        if any(w in desc for w in ["critique", "incendie", "explosion", "hors service", "hs"]):
            return "P3 - Elevé"
        return "P2 - Moyen"


class GenericParser(FileParser):
    def can_parse(self, df: pd.DataFrame, filename: str, sheet: str) -> bool:
        return True

    def parse(self, df: pd.DataFrame, filename: str, sheet: str) -> List[Dict[str, Any]]:
        df.columns = [str(c).strip() for c in df.columns]
        cols_are_integers = all(c.isdigit() for c in df.columns)
        unnamed_count = sum(1 for c in df.columns if c.startswith("Unnamed:"))
        needs_header_fix = cols_are_integers or (unnamed_count > len(df.columns) / 2)

        if needs_header_fix and len(df) > 0:
            header_row_idx = None
            for i, row in df.iterrows():
                non_none = [v for v in row if str(v).strip() not in ["", "None", "nan"]]
                if len(non_none) >= 3:  
                    header_row_idx = i
                    break

            if header_row_idx is not None:
                new_headers = [str(v).strip() if v is not None else f"col_{j}"
                              for j, v in enumerate(df.iloc[header_row_idx])]
                df = df.iloc[header_row_idx + 1:].copy()
                df.columns = new_headers
            else:
                return []

        detected = SmartColumnDetector.detect_columns(df)

        col_act     = detected.get("action")
        col_stat    = detected.get("statut")
        col_resp    = detected.get("responsable")
        col_ent     = detected.get("entite")
        col_prio    = detected.get("priorite")
        col_ech     = detected.get("date_echeance")
        col_deb     = detected.get("date_debut")
        col_loc     = detected.get("localisation")
        col_constat = detected.get("constat")

        if not col_act:
            return []

        records = []
        for idx, row in df.iterrows():
            action = str(row.get(col_act, "")).strip()
            if not action or action.lower() in ["nan", "none", "", "na"]:
                continue

            records.append({
                "description":      action,
                "statut":           str(row.get(col_stat, "Non défini")).strip() if col_stat else "Non défini",
                "responsable":      str(row.get(col_resp, "Non assigné")).strip()[:250] if col_resp else "Non assigné",
                "entite":           str(row.get(col_ent, "Général")).strip()[:250] if col_ent else "Général",
                "priorite":         str(row.get(col_prio, "")).strip() if col_prio else "Non défini",
                "date_echeance":    row.get(col_ech) if col_ech else None,
                "date_debut":       row.get(col_deb) if col_deb else None,
                "localisation":     str(row.get(col_loc, "")).strip() if col_loc else None,
                "constat_original": str(row.get(col_constat, "")).strip() if col_constat else None,
                "source_detail":    f"{filename} ({sheet})",
                "ligne_source":     idx
            })
        return records

    def _find_column(self, df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        for col in df.columns:
            col_clean = str(col).strip().lower().replace("\n", " ").replace("  ", " ")
            for cand in candidates:
                cand_clean = cand.lower().replace("\n", " ").replace("  ", " ")
                if cand_clean in col_clean or col_clean in cand_clean:
                    return col
        return None


# ============================================================
# ORCHESTRATEUR ETL
# ============================================================

class ETLOrchestrator:
    def __init__(self, settings: Settings, logger: logging.Logger):
        self.settings = settings
        self.logger = logger
        self.engine = create_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.hash_gen = HashGenerator(settings.hash_algorithm)
        self.quality_engine = DataQualityEngine(logger)
        self.parsers: List[FileParser] = [
            PSMParser(),
            RecommandationsParser(),
            GenericParser()
        ]
        self.stats = {
            "files_processed": 0,
            "files_failed": 0,
            "records_read": 0,
            "records_inserted": 0,
            "records_rejected": 0,
            "records_duplicated": 0,
            "batches_executed": 0
        }

    def initialize_database(self, force_recreate: bool = False):
        """
        Si force_recreate=True : drop + recreate (réservé aux tests).
        En production (force_recreate=False) : CREATE IF NOT EXISTS uniquement.
        Utiliser Alembic pour les vraies migrations.
        """
        self.logger.info("Initialisation de la base de données...")
        db_name = self.settings.db_name
        base_url = self.settings.database_url.rsplit('/', 1)[0]

        try:
            temp_engine = create_engine(base_url)
            with temp_engine.connect() as conn:
                conn.execute(text(
                    f"CREATE DATABASE IF NOT EXISTS {db_name} "
                    f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                ))
                conn.commit()
                self.logger.info(f"Base de données '{db_name}' créée/vérifiée.")
        except Exception as e:
            self.logger.warning(f"Impossible de créer la base: {e}")
        finally:
            if 'temp_engine' in locals():
                temp_engine.dispose()

        if force_recreate:
            self.logger.warning("force_recreate=True: DROP ALL TABLES — NE PAS UTILISER EN PRODUCTION")
            Base.metadata.drop_all(self.engine)

        Base.metadata.create_all(self.engine)
        self.logger.info("Tables vérifiées/créées.")

        with self.SessionLocal() as session:
            self._seed_dimensions(session)
            session.commit()

        self.logger.info("Base de données initialisée.")

    def _seed_dimensions(self, session: Session):
        statuts_data = [
            ("FAIT", "Fait", Decimal("1.00")),
            ("EN_COURS", "En cours", Decimal("0.50")),
            ("PLANIFIE", "Planifié", Decimal("0.10")),
            ("NON_FAIT", "Non fait", Decimal("0.00")),
            ("NA", "N.A", Decimal("0.00")),
            ("NON_DEFINI", "Non défini", Decimal("0.00"))
        ]
        for code, libelle, ordre in statuts_data:
            if not session.query(Statut).filter_by(code_statut=code).first():
                session.add(Statut(code_statut=code, libelle=libelle, ordre_avancement=ordre))

        priorites_data = [
            ("P4", "P4 - Critique", 4),
            ("P3", "P3 - Elevé", 3),
            ("P2", "P2 - Moyen", 2),
            ("P1", "P1 - Faible", 1),
            ("ND", "Non défini", 0)
        ]
        for code, libelle, ordre in priorites_data:
            if not session.query(Priorite).filter_by(code_priorite=code).first():
                session.add(Priorite(code_priorite=code, libelle=libelle, ordre=ordre))

        sources_data = ["PSM", "NH3", "HT", "FF", "Audit", "Diagnostic", "Autre"]
        for src in sources_data:
            if not session.query(SourceType).filter_by(code_source=src).first():
                session.add(SourceType(code_source=src, libelle=src))

        session.commit()

    @contextmanager
    def _transaction(self):
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
            self.logger.debug("Transaction commitée")
        except Exception as e:
            session.rollback()
            self.logger.error(f"Transaction rollback: {e}")
            raise
        finally:
            session.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, OSError))
    )
    def process_file(self, filepath: Path) -> int:
        filename = filepath.name
        self.logger.info(f"Traitement de {filename}...")

        try:
            if filename.endswith(".csv"):
                dfs = {"Feuil1": pd.read_csv(filepath)}
            else:
                try:
                    xls = pd.ExcelFile(str(filepath), engine='openpyxl')
                    dfs = {}
                    for sheet in xls.sheet_names:
                        try:
                            dfs[sheet] = pd.read_excel(str(filepath), sheet_name=sheet, header=None, engine='openpyxl')
                        except Exception as sheet_e:
                            self.logger.warning(f"Onglet '{sheet}' ignoré dans {filename}: {sheet_e}")
                except Exception as direct_error:
                    self.logger.warning(f"Lecture directe échouée pour {filename}: {direct_error}")
                    self.logger.info("Tentative de réparation avec openpyxl...")

                    import openpyxl
                    import tempfile

                    wb = openpyxl.load_workbook(str(filepath), data_only=True)
                    for sheet_name in wb.sheetnames:
                        ws = wb[sheet_name]
                        if ws.auto_filter:
                            ws.auto_filter = None

                    fd, temp_path = tempfile.mkstemp(suffix='.xlsx')
                    os.close(fd)

                    try:
                        wb.save(temp_path)
                        wb.close()
                        xls = pd.ExcelFile(temp_path, engine='openpyxl')
                        dfs = {}
                        for sheet in xls.sheet_names:
                            try:
                                dfs[sheet] = pd.read_excel(temp_path, sheet_name=sheet, header=None, engine='openpyxl')
                            except Exception as sheet_e:
                                self.logger.warning(f"Onglet '{sheet}' ignoré: {sheet_e}")
                    finally:
                        try:
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                        except Exception as cleanup_e:
                            self.logger.warning(f"Impossible de supprimer le fichier temporaire: {cleanup_e}")

        except Exception as e:
            self.logger.error(f"Erreur lecture {filename}: {e}")
            self.stats["files_failed"] += 1
            return 0

        total_inserted = 0
        batch_id = hashlib.sha256(f"{filename}_{datetime.utcnow().isoformat()}".encode()).hexdigest()[:16]

        for sheet_name, df in dfs.items():
            if df.empty or len(df) < 2:
                continue

            parser = None
            for p in self.parsers:
                if p.can_parse(df, filename, sheet_name):
                    parser = p
                    break

            if not parser:
                self.logger.warning(f"Aucun parser trouvé pour {filename}/{sheet_name}")
                continue

            records = parser.parse(df, filename, sheet_name)
            self.stats["records_read"] += len(records)

            valid_records = []
            for rec in records:
                is_valid, messages = self.quality_engine.validate(rec, f"{filename}:{sheet_name}")
                if is_valid:
                    valid_records.append(rec)
                else:
                    self.stats["records_rejected"] += 1
                    self.logger.warning(f"Rejeté: {messages}")

            if valid_records:
                inserted = self._load_batch(valid_records, batch_id, filename, sheet_name)
                total_inserted += inserted

        self.stats["files_processed"] += 1
        return total_inserted

    def _load_batch(self, records: List[Dict], batch_id: str, filename: str, sheet: str) -> int:
        src_type = SourceTypeDetector.detect(filename)
        inserted_count = 0

        with self._transaction() as session:
            for i in range(0, len(records), self.settings.batch_size):
                batch = records[i:i + self.settings.batch_size]

                for rec in batch:
                    entite_code = self._normalize_entite(rec.get("entite", "Général"))
                    resp_name = rec.get("responsable", "Non assigné")
                    statut_code = self._normalize_statut(rec.get("statut", "Non défini"))
                    prio_code = self._normalize_priorite(rec.get("priorite", "Non défini"))
                    date_ech = DateParser.parse(rec.get("date_echeance"))
                    date_deb = DateParser.parse(rec.get("date_debut"))

                    entite_id = self._get_or_create_dimension(
                        session, Entite, "code_entite", entite_code,
                        {"nom_entite": entite_code}
                    )
                    resp_id = self._get_or_create_dimension(session, Responsable, "nom_complet", resp_name)
                    statut_id = self._get_or_create_dimension(session, Statut, "code_statut", statut_code)
                    prio_id = self._get_or_create_dimension(session, Priorite, "code_priorite", prio_code)
                    src_id = self._get_or_create_dimension(session, SourceType, "code_source", src_type)

                    action_hash = self.hash_gen.generate(
                        rec["description"], resp_name, entite_code,
                        f"{filename}|{rec.get('localisation', '')}",
                        date_ech
                    )

                    existing = session.query(ActionFact).filter(
                        ActionFact.action_key == action_hash,
                        ActionFact.est_actif == 1
                    ).first()

                    if existing:
                        
                        if (existing.id_statut == statut_id and
                            existing.id_priorite == prio_id and
                            existing.description_action == rec["description"]):
                            self.stats["records_duplicated"] += 1
                            self.logger.debug(f"Duplicate skipped: {rec['description'][:50]}")
                            continue
                        
                        if (existing.id_statut != statut_id or
                            existing.id_priorite != prio_id):
                            existing.date_fin_validite = datetime.utcnow()
                            existing.est_actif = 0
                        else:
                            self.stats["records_duplicated"] += 1
                            continue

                    new_action = ActionFact(
                        action_key=action_hash,
                        id_entite=entite_id,
                        id_responsable=resp_id,
                        id_statut=statut_id,
                        id_priorite=prio_id,
                        id_source_type=src_id,
                        description_action=rec["description"],
                        localisation=rec.get("localisation"),
                        constat_original=rec.get("constat_original"),
                        recommandation=rec.get("recommandation"),
                        date_echeance=date_ech,
                        date_realisation=date_deb if statut_code == "FAIT" else None,
                        fichier_source=filename,
                        sheet_source=sheet,
                        ligne_source=rec.get("ligne_source"),
                        import_batch_id=batch_id,
                        est_actif=1
                    )

                    session.add(new_action)
                    inserted_count += 1

                session.flush()
                self.stats["batches_executed"] += 1

        self.stats["records_inserted"] += inserted_count
        return inserted_count

    def _get_or_create_dimension(self, session: Session, model, code_field: str,
                                  code_value: str, extra_fields: Dict = None) -> int:
        existing = session.query(model).filter(
            getattr(model, code_field) == code_value
        ).first()

        pk_attr = _MODEL_PK_MAP.get(model.__name__, "id") 

        if existing:
            return getattr(existing, pk_attr)

        new_obj = model(**{code_field: code_value})
        if extra_fields:
            for k, v in extra_fields.items():
                setattr(new_obj, k, v)

        session.add(new_obj)
        session.flush()
        return getattr(new_obj, pk_attr)

    def _normalize_entite(self, raw: str) -> str:
        r = str(raw).upper().strip()
        mapping = {
            "JFC1": "JFC1", "JFC-1": "JFC1", "JLS": "JFC1",
            "JFC2": "JFC2", "JFC 2": "JFC2",
            "JFC5": "JFC5", "JFC 5": "JFC5",
            "KOFERT": "KOFERT", "EMAPHOS": "EMAPHOS", "EMAPHOS 1": "EMAPHOS",
            "IMACID": "IMACID", "PMP": "PMP", "DESSALEMENT": "DESSALEMENT",
            "NA": "SITE", "TOUTES LES ENTITÉS": "SITE", "SITE": "SITE"
        }
        return mapping.get(r, r)

    def _normalize_statut(self, raw: str) -> str:
        r = str(raw).lower().strip()
        if "non fait" in r: return "NON_FAIT"
        if "en cours" in r: return "EN_COURS"
        if "planif" in r: return "PLANIFIE"
        if "n.a" in r or r == "na" or r == "n/a": return "NA"
        if "fait" in r: return "FAIT"
        return "NON_DEFINI"

    def _normalize_priorite(self, raw: str) -> str:
        r = str(raw).lower().strip()
        if "p4" in r or "critique" in r: return "P4"
        if "p3" in r or "elev" in r or "élevé" in r: return "P3"
        if "p2" in r or "moyen" in r: return "P2"
        if "p1" in r or "faible" in r: return "P1"
        r_num = r.replace(".0", "").strip()
        if r_num == "4": return "P4"
        if r_num == "3": return "P3"
        if r_num == "2": return "P2"
        if r_num == "1": return "P1"
        return "ND"

    def run(self):
        self.logger.info("=" * 60)
        self.logger.info("DÉMARRAGE ETL SFE v3")
        self.logger.info("=" * 60)

        self.initialize_database()

        (self.quality_engine
             .add_rule(NotEmptyRule("description"))
             .add_rule(DateFormatRule("date_echeance"))
             .add_rule(PriorityConsistencyRule()))

        data_path = self.settings.data_folder
        if not data_path.exists():
            self.logger.error(f"Dossier {data_path} introuvable")
            return

        files = list(data_path.glob("*.xlsx")) + list(data_path.glob("*.csv"))
        files = [f for f in files if not f.name.startswith("~$")]
        self.logger.info(f"{len(files)} fichier(s) détecté(s)")

        for filepath in files:
            self.process_file(filepath)

        self._print_report()

    def _print_report(self):
        self.logger.info("=" * 60)
        self.logger.info("RAPPORT D'IMPORT")
        self.logger.info("=" * 60)
        for key, val in self.stats.items():
            self.logger.info(f"  {key:25s}: {val}")

        quality_report = self.quality_engine.get_report()
        self.logger.info(f"\nQualité des données:")
        self.logger.info(f"  Règles actives: {quality_report['total_rules']}")
        self.logger.info(f"  Problèmes détectés: {quality_report['total_issues']}")
        if quality_report['issues_by_type']:
            self.logger.info(f"  Répartition: {quality_report['issues_by_type']}")
        self.logger.info("=" * 60)


# ============================================================
# POINT D'ENTRÉE
# ============================================================

if __name__ == "__main__":
    try:
        settings = Settings()
        logger = setup_logging(settings)
        logger.info(f"Base de données: {settings.db_host}:{settings.db_port}/{settings.db_name}")

        orchestrator = ETLOrchestrator(settings, logger)
        orchestrator.run()

    except Exception as e:
        print(f"\nERREUR FATALE: {e}")
        print("\nVérifie que ton fichier .env existe avec:")
        print("   DB_HOST=127.0.0.1")
        print("   DB_PORT=3306")
        print("   DB_USER=root")
        print("   DB_PASSWORD=TonMotDePasse")
        print("   DB_NAME=sfe_dwh")
        sys.exit(1)