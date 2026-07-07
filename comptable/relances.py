"""
Relances impayés automatiques.
Gère les scénarios de relance et l'historique des relances envoyées.
Pas d'envoi d'emails réels, juste logging.
"""

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional

from .db import get_db


def creer_scenario(
    nom: str,
    conditions_json: str,
    modele_email: str,
    delai_jours: int,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Crée un scénario de relance et retourne son ID."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    cur = conn.execute(
        """INSERT INTO scenarios_relance (nom, conditions_json, modele_email, delai_jours)
           VALUES (?, ?, ?, ?)""",
        (nom, conditions_json, modele_email, delai_jours),
    )
    sid = cur.lastrowid

    if doit_fermer:
        conn.commit()
        conn.close()
    return sid


def lister_scenarios(conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    """Liste tous les scénarios de relance."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    rows = conn.execute(
        "SELECT * FROM scenarios_relance ORDER BY created_at DESC"
    ).fetchall()

    if doit_fermer:
        conn.close()
    return [dict(r) for r in rows]


def supprimer_scenario(
    scenario_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Supprime un scénario de relance."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    conn.execute("DELETE FROM scenarios_relance WHERE id = ?", (scenario_id,))

    if doit_fermer:
        conn.commit()
        conn.close()
    return {"ok": True, "id": scenario_id}


def executer_relances(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """
    Parcourt les factures en retard et applique les scénarios actifs.
    Enregistre l'historique des relances. Pas d'envoi d'email réel.
    Retourne {nb_relances, details: [{facture_id, scenario_nom, client, montant}]}.
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    today = date.today()

    # Factures en retard : statut non payée/annulée et échéance dépassée
    factures = conn.execute(
        """SELECT id, client_nom, total_ttc, date, echeance, statut
           FROM factures
           WHERE exercice_id = ?
             AND type = 'facture'
             AND statut NOT IN ('payee', 'annulee')
           ORDER BY echeance, id""",
        (exercice_id,),
    ).fetchall()

    # Scénarios actifs
    scenarios = conn.execute(
        "SELECT * FROM scenarios_relance WHERE actif = 1 ORDER BY delai_jours"
    ).fetchall()

    details = []
    nb_relances = 0

    for fact in factures:
        fact_date = fact["echeance"] or fact["date"]
        try:
            d = datetime.strptime(fact_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        retard_jours = (today - d).days
        if retard_jours <= 0:
            continue

        for scenario in scenarios:
            # Vérifie si ce scénario s'applique (retard >= delai du scénario)
            if retard_jours < scenario["delai_jours"]:
                continue

            # Vérifie qu'on n'a pas déjà envoyé cette relance
            already = conn.execute(
                """SELECT id FROM historique_relances
                   WHERE facture_id = ? AND scenario_id = ?""",
                (fact["id"], scenario["id"]),
            ).fetchone()
            if already:
                continue

            # Enregistre la relance
            message = f"[RELANCE] Facture {fact['id']} — Client: {fact['client_nom'] or '?'} — "
            message += f"Retard: {retard_jours}j — Scénario: {scenario['nom']}"

            conn.execute(
                """INSERT INTO historique_relances (facture_id, scenario_id, message)
                   VALUES (?, ?, ?)""",
                (fact["id"], scenario["id"], message),
            )

            # Log (pas de vrai email)
            print(f"[compta/relances] {message}")

            details.append({
                "facture_id": fact["id"],
                "scenario_nom": scenario["nom"],
                "client": fact["client_nom"] or "Client divers",
                "montant": round(fact["total_ttc"] or 0, 2),
                "retard_jours": retard_jours,
            })
            nb_relances += 1

    if doit_fermer:
        conn.commit()
        conn.close()

    return {"nb_relances": nb_relances, "details": details}


def historique_relances(
    facture_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Retourne l'historique des relances pour une facture donnée."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    rows = conn.execute(
        """SELECT h.*, s.nom as scenario_nom
           FROM historique_relances h
           LEFT JOIN scenarios_relance s ON s.id = h.scenario_id
           WHERE h.facture_id = ?
           ORDER BY h.date_envoi DESC""",
        (facture_id,),
    ).fetchall()

    if doit_fermer:
        conn.close()
    return [dict(r) for r in rows]


def resume_relances(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """
    Résumé des relances : nombre de factures en retard,
    et répartition par tranche de retard (7j, 15j, 30j+).
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    today = date.today()
    factures = conn.execute(
        """SELECT id, date, echeance, total_ttc
           FROM factures
           WHERE exercice_id = ?
             AND type = 'facture'
             AND statut NOT IN ('payee', 'annulee')
           ORDER BY echeance, id""",
        (exercice_id,),
    ).fetchall()

    nb_retard = 0
    nb_j7 = 0
    nb_j15 = 0
    nb_j30 = 0

    for f in factures:
        ref_date = f["echeance"] or f["date"]
        try:
            d = datetime.strptime(ref_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        retard = (today - d).days
        if retard <= 0:
            continue
        nb_retard += 1
        if retard <= 7:
            nb_j7 += 1
        elif retard <= 15:
            nb_j15 += 1
        else:
            nb_j30 += 1

    if doit_fermer:
        conn.close()

    return {
        "nb_retard": nb_retard,
        "nb_relances_j7": nb_j7,
        "nb_relances_j15": nb_j15,
        "nb_relances_j30": nb_j30,
    }
