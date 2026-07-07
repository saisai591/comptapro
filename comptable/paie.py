"""
Import d'OD de paie (PayFit, Silae, générique).

Format CSV standard : compte, libelle, debit, credit, date
"""

import csv
import os
import sqlite3
from datetime import date
from typing import Optional

from .db import get_db
from .ecritures import saisir_ecriture


def detecter_format(chemin_fichier: str) -> str:
    """Détecte le format du CSV de paie basé sur les en-têtes."""
    with open(chemin_fichier, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = [h.strip().lower() for h in next(reader, [])]

    header_str = ",".join(headers)
    if "salaire_brut" in header_str or "payfit" in header_str:
        return "payfit"
    if "matricule" in header_str or "silae" in header_str:
        return "silae"
    return "generique"


def importer_paie_csv(
    exercice_id: int,
    chemin_fichier: str,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """
    Parse un CSV d'OD de paie et crée une écriture groupée.
    Retourne {nb_ecritures, total_debit, total_credit, equilibre, format}.
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    if not os.path.exists(chemin_fichier):
        raise FileNotFoundError(f"Fichier introuvable : {chemin_fichier}")

    fmt = detecter_format(chemin_fichier)
    lignes_ecriture = []
    total_debit = 0.0
    total_credit = 0.0
    date_paie = date.today().isoformat()

    with open(chemin_fichier, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            compte = (
                row.get("compte") or row.get("Compte")
                or row.get("Compte") or ""
            ).strip()
            libelle = (
                row.get("libelle") or row.get("Libelle")
                or row.get("Libellé") or ""
            ).strip()
            debit_str = (
                row.get("debit") or row.get("Debit")
                or row.get("Débit") or "0"
            ).strip()
            credit_str = (
                row.get("credit") or row.get("Credit")
                or row.get("Crédit") or "0"
            ).strip()
            date_col = (
                row.get("date") or row.get("Date") or ""
            ).strip()

            if not compte:
                continue

            try:
                debit = float(debit_str.replace(",", ".") or 0)
            except (ValueError, AttributeError):
                debit = 0.0
            try:
                credit = float(credit_str.replace(",", ".") or 0)
            except (ValueError, AttributeError):
                credit = 0.0

            if date_col:
                date_paie = date_col

            lignes_ecriture.append({
                "compte": compte,
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "libelle": libelle or f"OD Paie — {compte}",
            })
            total_debit += debit
            total_credit += credit

    total_debit = round(total_debit, 2)
    total_credit = round(total_credit, 2)
    equilibre = abs(total_debit - total_credit) < 0.01

    if lignes_ecriture:
        saisir_ecriture(
            exercice_id, "OD", date_paie,
            f"OD Paie ({fmt}) — {date_paie}",
            lignes_ecriture,
            conn=conn,
        )

    if doit_fermer:
        conn.close()

    return {
        "nb_ecritures": 1 if lignes_ecriture else 0,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "equilibre": equilibre,
        "format": fmt,
    }


def modele_paie(exercice_id: int) -> dict:
    """Template d'OD de paie type (sans DSN).
    exercice_id conservé pour cohérence d'API bien que non utilisé ici.
    """
    return {
        "description": "Modèle d'OD de paie standard — comptes usuels",
        "lignes": [
            {"compte": "641", "libelle": "Salaires bruts", "sens": "debit"},
            {"compte": "6451", "libelle": "Cotisations URSSAF", "sens": "debit"},
            {"compte": "6452", "libelle": "Cotisations mutuelle", "sens": "debit"},
            {"compte": "6453", "libelle": "Cotisations retraite", "sens": "debit"},
            {"compte": "6454", "libelle": "Cotisations ASSEDIC", "sens": "debit"},
            {"compte": "421", "libelle": "Salaires nets à payer", "sens": "credit"},
            {"compte": "431", "libelle": "URSSAF à payer", "sens": "credit"},
            {"compte": "4371", "libelle": "Mutuelle à payer", "sens": "credit"},
            {"compte": "4372", "libelle": "Retraite à payer", "sens": "credit"},
            {"compte": "4373", "libelle": "ASSEDIC à payer", "sens": "credit"},
        ],
    }
