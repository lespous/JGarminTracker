"""Certificats racine du système pour les appels HTTPS vers Garmin.

Sur un PC d'entreprise, un proxy (Cisco Umbrella, Zscaler…) intercepte le HTTPS et signe avec sa propre
autorité, connue de Windows mais pas de Python (certifi). On construit un fichier PEM = certifi + racines
de confiance de Windows, et on le donne à requests et curl_cffi par les variables d'environnement
qu'ils lisent. Doit être appelé AVANT d'importer garminconnect (curl_cffi lit la variable à l'import).

Désactivable avec JGARMIN_SYSTEM_CERTS=0. Sans effet si SSL_CERT_FILE / REQUESTS_CA_BUNDLE est déjà défini.
"""

from __future__ import annotations

import os
import ssl
from pathlib import Path

ENV_VARS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
SERVER_AUTH = "1.3.6.1.5.5.7.3.1"


def windows_roots() -> list[str]:
    """Certificats racine (et intermédiaires) de confiance du magasin Windows, au format PEM."""
    if not hasattr(ssl, "enum_certificates"):  # pas sous Windows
        return []
    pems: list[str] = []
    for store in ("ROOT", "CA"):
        try:
            entries = ssl.enum_certificates(store)
        except OSError:
            continue
        for der, encoding, trust in entries:
            if encoding == "x509_asn" and (trust is True or SERVER_AUTH in trust):
                pems.append(ssl.DER_cert_to_PEM_cert(der))
    return pems


def bundle_path() -> Path:
    return Path.home() / ".jgarmin" / "ca-bundle.pem"


def build_bundle(path: Path | None = None) -> Path | None:
    """Écrit certifi + racines Windows dans path. None s'il n'y a rien à ajouter à certifi."""
    import certifi

    extra = windows_roots()
    if not extra:
        return None
    path = path or bundle_path()
    content = Path(certifi.where()).read_text(encoding="ascii") + "\n" + "".join(dict.fromkeys(extra))
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="ascii") != content:
        path.write_text(content, encoding="ascii")
    return path


def use_system_certificates() -> Path | None:
    """Active le fichier de certificats pour ce processus. Renvoie son chemin, ou None si inutile/désactivé."""
    if os.environ.get("JGARMIN_SYSTEM_CERTS") == "0" or any(os.environ.get(v) for v in ENV_VARS[:2]):
        return None
    try:
        path = build_bundle()
    except OSError:
        return None
    if path:
        for var in ENV_VARS:
            os.environ.setdefault(var, str(path))
    return path
