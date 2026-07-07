"""
Piste d'audit : enregistrement des actions sur les entités.
Stdlib uniquement.
"""

import json
import sqlite3
from datetime import datetime
from typing import Optional

from .db import get_db


def log_action(
    entite_type: str,
    entite_id: int,
    action: str,
    details: Optional[dict] = None,
    utilisateur: str = "systeme",
):
    """Enregistre une entrée dans la piste d'audit.
    Utilise une nouvelle connexion avec commit immédiat pour garantir
    l'écriture même en cas d'erreur dans la transaction appelante.
    """
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO piste_audit (entite_type, entite_id, action, details, utilisateur)
               VALUES (?, ?, ?, ?, ?)""",
            (entite_type, entite_id, action,
             json.dumps(details, ensure_ascii=False, default=str) if details else None,
             utilisateur),
        )
        conn.commit()
    finally:
        conn.close()


def historique_entite(entite_type: str, entite_id: int) -> list[dict]:
    """Retourne l'historique des actions pour une entité donnée."""
    conn = get_db()
    rows = conn.execute(
        """SELECT created_at as date, action, details, utilisateur
           FROM piste_audit
           WHERE entite_type = ? AND entite_id = ?
           ORDER BY id DESC""",
        (entite_type, entite_id),
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        try:
            d["details"] = json.loads(d["details"]) if d.get("details") else None
        except (json.JSONDecodeError, TypeError):
            pass
        result.append(d)
    return result


def dernieres_actions(limite: int = 20) -> list[dict]:
    """Retourne les dernières entrées d'audit globales."""
    conn = get_db()
    rows = conn.execute(
        """SELECT id, entite_type, entite_id, action, details, utilisateur, created_at
           FROM piste_audit
           ORDER BY id DESC
           LIMIT ?""",
        (limite,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
