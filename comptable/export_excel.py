"""
Export CSV des données comptables.

Génère des fichiers CSV tabulés pour la balance, le grand-livre,
les écritures, les factures, le bilan, et un CSV par journal.

Stdlib uniquement (csv, os).
"""

import csv
import os
import sqlite3
from typing import Optional

from .db import get_db


# ── helpers CSV ──────────────────────────────────────────────────────

def _write_csv(chemin: str, entetes: list[str], lignes: list[list], delimiter: str = ",") -> int:
    """Écrit un CSV sur disque. Retourne le nombre de lignes (hors en-tête)."""
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=delimiter)
        w.writerow(entetes)
        for row in lignes:
            w.writerow(row)
    return len(lignes)


# ── balance ──────────────────────────────────────────────────────────

def exporter_balance_csv(
    exercice_id: int,
    chemin_fichier: str,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Export CSV tabulé de la balance générale."""
    from .balance import balance_generale

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    balance = balance_generale(exercice_id, conn=conn)

    lignes = []
    for l in balance:
        lignes.append([
            l["compte"],
            str(l["total_debit"]).replace(".", ","),
            str(l["total_credit"]).replace(".", ","),
            str(l["solde_debit"]).replace(".", ","),
            str(l["solde_credit"]).replace(".", ","),
        ])

    if doit_fermer:
        conn.close()

    return _write_csv(
        chemin_fichier,
        ["Compte", "Total Débit", "Total Crédit", "Solde Débiteur", "Solde Créditeur"],
        lignes,
    )


# ── grand-livre ──────────────────────────────────────────────────────

def exporter_grand_livre_csv(
    exercice_id: int,
    chemin_fichier: str,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Export CSV du grand-livre complet (tous comptes)."""
    from .grand_livre import grand_livre as gl_complet

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    gl = gl_complet(exercice_id, conn=conn)

    lignes = []
    for compte in gl:
        # Ligne de solde d'ouverture
        lignes.append([
            compte["compte"],
            "",
            "",
            "SOLDE OUVERTURE",
            str(compte["solde_ouverture"]).replace(".", ","),
            "",
            "",
        ])
        for m in compte["mouvements"]:
            lignes.append([
                compte["compte"],
                m["date"],
                m["journal"],
                m["piece"] or "",
                m["libelle"],
                str(m["debit"]).replace(".", ","),
                str(m["credit"]).replace(".", ","),
                str(m["solde_cumul"]).replace(".", ","),
            ])
        # Ligne de totaux
        lignes.append([
            compte["compte"],
            "",
            "",
            "TOTAL COMPTE",
            "",
            str(compte["total_debit"]).replace(".", ","),
            str(compte["total_credit"]).replace(".", ","),
            str(compte["solde_final"]).replace(".", ","),
        ])
        lignes.append([])  # séparateur vide

    if doit_fermer:
        conn.close()

    return _write_csv(
        chemin_fichier,
        ["Compte", "Date", "Journal", "Pièce", "Libellé", "Débit", "Crédit", "Solde"],
        lignes,
    )


# ── écritures ────────────────────────────────────────────────────────

def exporter_ecritures_csv(
    exercice_id: int,
    chemin_fichier: str,
    journal: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Export CSV des écritures avec toutes les lignes (partie double)."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    query = """
        SELECT e.id, e.journal, e.date, e.piece, e.reference,
               e.libelle AS ecriture_libelle,
               l.compte, l.debit, l.credit, l.libelle AS ligne_libelle,
               l.auxiliaire_id
        FROM ecritures e
        JOIN lignes_ecriture l ON l.ecriture_id = e.id
        WHERE e.exercice_id = ?
    """
    params = [exercice_id]
    if journal:
        query += " AND e.journal = ?"
        params.append(journal)
    query += " ORDER BY e.date, e.id, l.id"

    rows = conn.execute(query, params).fetchall()

    lignes = []
    for r in rows:
        aux_nom = ""
        if r["auxiliaire_id"]:
            aux = conn.execute(
                "SELECT nom FROM comptes_aux WHERE id = ?", (r["auxiliaire_id"],)
            ).fetchone()
            if aux:
                aux_nom = aux["nom"]

        lignes.append([
            str(r["id"]),
            r["date"],
            r["journal"],
            r["piece"] or "",
            r["reference"] or "",
            r["ecriture_libelle"],
            r["compte"],
            aux_nom,
            str(r["debit"] or 0).replace(".", ","),
            str(r["credit"] or 0).replace(".", ","),
            r["ligne_libelle"] or "",
        ])

    if doit_fermer:
        conn.close()

    return _write_csv(
        chemin_fichier,
        ["Écriture ID", "Date", "Journal", "Pièce", "Référence",
         "Libellé Écriture", "Compte", "Auxiliaire", "Débit", "Crédit", "Libellé Ligne"],
        lignes,
    )


# ── journaux ─────────────────────────────────────────────────────────

def exporter_journaux_csv(
    exercice_id: int,
    dossier_sortie: str,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """
    Exporte un CSV par journal dans le dossier indiqué.
    Retourne {journal: nb_lignes, ...}.
    """
    from .ecritures import JOURNAUX

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    # Récupérer les journaux réellement utilisés dans cet exercice
    journaux = conn.execute(
        "SELECT DISTINCT journal FROM ecritures WHERE exercice_id = ? ORDER BY journal",
        (exercice_id,),
    ).fetchall()

    resultats = {}
    for j in journaux:
        code = j["journal"]
        fichier = os.path.join(dossier_sortie, f"{code}.csv")
        nb = exporter_ecritures_csv(exercice_id, fichier, journal=code, conn=conn)
        resultats[code] = nb

    if doit_fermer:
        conn.close()

    return resultats


# ── factures ─────────────────────────────────────────────────────────

def exporter_factures_csv(
    exercice_id: int,
    chemin_fichier: str,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Export CSV de toutes les factures avec leurs lignes."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    rows = conn.execute(
        """SELECT f.id, f.type, f.numero, f.date, f.echeance,
                  f.client_nom, f.client_email, f.statut,
                  f.total_ht, f.total_tva, f.total_ttc, f.notes,
                  lf.description, lf.quantite, lf.prix_unitaire, lf.tva_taux
           FROM factures f
           LEFT JOIN lignes_facture lf ON lf.facture_id = f.id
           WHERE f.exercice_id = ?
           ORDER BY f.date, f.id, lf.id""",
        (exercice_id,),
    ).fetchall()

    lignes = []
    for r in rows:
        lignes.append([
            r["type"],
            r["numero"],
            r["date"],
            r["echeance"] or "",
            r["client_nom"] or "",
            r["client_email"] or "",
            r["statut"],
            str(r["total_ht"] or 0).replace(".", ","),
            str(r["total_tva"] or 0).replace(".", ","),
            str(r["total_ttc"] or 0).replace(".", ","),
            r["notes"] or "",
            r["description"] or "",
            str(r["quantite"] or 0).replace(".", ","),
            str(r["prix_unitaire"] or 0).replace(".", ","),
            str(r["tva_taux"] or 0).replace(".", ","),
        ])

    if doit_fermer:
        conn.close()

    return _write_csv(
        chemin_fichier,
        ["Type", "Numéro", "Date", "Échéance", "Client", "Email", "Statut",
         "Total HT", "Total TVA", "Total TTC", "Notes",
         "Description Ligne", "Quantité", "Prix Unitaire", "Taux TVA"],
        lignes,
    )


# ── bilan ────────────────────────────────────────────────────────────

def exporter_bilan_csv(
    exercice_id: int,
    chemin_fichier: str,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Export CSV du bilan synthétique (actif / passif)."""
    from .balance import bilan_synthetique

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    bilan = bilan_synthetique(exercice_id, conn=conn)

    lignes = []

    lignes.append(["ACTIF", "", "", "", ""])
    for l in bilan["actif"]:
        lignes.append([
            l["compte"],
            l.get("libelle", ""),
            str(l["solde_debit"]).replace(".", ","),
            str(l["total_debit"]).replace(".", ","),
            str(l["total_credit"]).replace(".", ","),
        ])
    lignes.append(["TOTAL ACTIF", "", str(bilan["total_actif"]).replace(".", ","), "", ""])
    lignes.append([])

    lignes.append(["PASSIF", "", "", "", ""])
    for l in bilan["passif"]:
        lignes.append([
            l["compte"],
            l.get("libelle", ""),
            str(l["solde_credit"]).replace(".", ","),
            str(l["total_debit"]).replace(".", ","),
            str(l["total_credit"]).replace(".", ","),
        ])
    lignes.append(["TOTAL PASSIF", "", str(bilan["total_passif"]).replace(".", ","), "", ""])

    if doit_fermer:
        conn.close()

    return _write_csv(
        chemin_fichier,
        ["Compte", "Libellé", "Solde", "Total Débit", "Total Crédit"],
        lignes,
    )
