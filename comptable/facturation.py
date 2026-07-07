"""
Facturation : création, listing, génération d'écritures, balance âgée.
"""

import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional

from .db import get_db


def _next_numero(conn, typ: str, annee: str = "") -> str:
    """Génère le prochain numéro de facture/devis. Format: FAC-2025-0001."""
    if not annee:
        annee = str(date.today().year)

    num = conn.execute(
        "SELECT valeur FROM parametres WHERE cle='prochain_numero'"
    ).fetchone()
    current = int(num["valeur"]) if num else 1

    conn.execute(
        "INSERT INTO parametres (cle, valeur) VALUES ('prochain_numero', ?) "
        "ON CONFLICT(cle) DO UPDATE SET valeur=valeur+1",
        (str(current + 1),),
    )

    code = {"facture": "FAC", "devis": "DEV", "avoir": "AVO"}.get(typ.lower(), "FAC")
    return f"{code}-{annee}-{current:04d}"


def creer_facture(
    exercice_id: int,
    typ: str,
    date_str: str,
    lignes: list[dict],
    client_id: Optional[int] = None,
    client_nom: Optional[str] = None,
    client: Optional[str] = None,
    client_adresse: Optional[str] = None,
    client_email: Optional[str] = None,
    client_siret: Optional[str] = None,
    echeance: Optional[str] = None,
    notes: Optional[str] = None,
    statut: str = "brouillon",
    objet: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Crée une facture/devis/avoir et retourne son ID."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    # Alias client = client_nom
    if client and not client_nom:
        client_nom = client

    annee = date_str[:4] if date_str and len(date_str) >= 4 else str(date.today().year)
    numero = _next_numero(conn, typ, annee)

    total_ht = sum((l.get("quantite", 1) or 1) * (l.get("prix_unitaire", 0) or 0) for l in lignes)
    total_tva = sum(
        (l.get("quantite", 1) or 1) * (l.get("prix_unitaire", 0) or 0) * (l.get("tva_taux", 20) or 0) / 100
        for l in lignes
    )
    total_ttc = round(total_ht + total_tva, 2)

    cur = conn.execute(
        """INSERT INTO factures (exercice_id, type, numero, date, echeance,
           client_id, client_nom, client_adresse, client_email, client_siret,
           statut, total_ht, total_tva, total_ttc, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (exercice_id, typ.lower(), numero, date_str, echeance,
         client_id, client_nom, client_adresse, client_email, client_siret,
         statut, round(total_ht, 2), round(total_tva, 2), total_ttc, notes),
    )
    facture_id = cur.lastrowid

    for ligne in lignes:
        conn.execute(
            "INSERT INTO lignes_facture (facture_id, description, quantite, prix_unitaire, tva_taux) "
            "VALUES (?,?,?,?,?)",
            (facture_id,
             ligne.get("description", ""),
             ligne.get("quantite", 1) or 1,
             ligne.get("prix_unitaire", 0) or 0,
             ligne.get("tva_taux", 20) or 0),
        )

    if doit_fermer:
        conn.commit()
        conn.close()
    return facture_id


def lister_factures(
    exercice_id: int,
    typ: Optional[str] = None,
    statut: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Liste les factures d'un exercice avec filtres optionnels."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    query = "SELECT * FROM factures WHERE exercice_id = ?"
    params = [exercice_id]
    if typ:
        query += " AND type = ?"
        params.append(typ.lower())
    if statut:
        statut_map = {"retard": "en_retard", "envoyé": "envoyee", "payé": "payee", "envoyee": "envoyee"}
        params.append(statut_map.get(statut.lower(), statut.lower()))
        query += " AND statut = ?"

    query += " ORDER BY date DESC, id DESC"
    rows = conn.execute(query, params).fetchall()

    if doit_fermer:
        conn.close()
    result = [dict(r) for r in rows]
    # Renommer client_nom → client pour le frontend
    for r in result:
        if "client_nom" in r:
            r["client"] = r.pop("client_nom")
    return result


def facture_detail(facture_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    """Détail complet d'une facture avec ses lignes."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    f = conn.execute("SELECT * FROM factures WHERE id = ?", (facture_id,)).fetchone()
    if not f:
        if doit_fermer:
            conn.close()
        return None

    lignes = conn.execute(
        "SELECT * FROM lignes_facture WHERE facture_id = ?", (facture_id,)
    ).fetchall()

    result = dict(f)
    result["lignes"] = [dict(l) for l in lignes]

    if doit_fermer:
        conn.close()
    return result


def generer_ecriture_facture(
    facture_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """
    Génère l'écriture comptable correspondant à une facture.
    - Facture client : débit 411, crédit 7xx + 4457
    - Facture fournisseur (non géré ici).
    Retourne l'ID de l'écriture créée.
    """
    from .ecritures import saisir_ecriture

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    row = conn.execute("SELECT * FROM factures WHERE id = ?", (facture_id,)).fetchone()
    if not row:
        if doit_fermer:
            conn.close()
        raise ValueError(f"Facture {facture_id} introuvable")
    fact = dict(row)

    if fact["ecriture_id"]:
        if doit_fermer:
            conn.close()
        raise ValueError("Une écriture existe déjà pour cette facture")

    lignes_f = conn.execute(
        "SELECT * FROM lignes_facture WHERE facture_id = ?", (facture_id,)
    ).fetchall()

    ecriture_lignes = []
    # Ligne client (débit)
    ecriture_lignes.append({
        "compte": "411",
        "debit": round(fact["total_ttc"], 2),
        "credit": 0,
        "libelle": fact.get("client_nom") or "Client",
    })

    # Lignes de produits (crédit)
    produits = {}
    tva_par_taux = {}
    for lf in lignes_f:
        ht = (lf["quantite"] or 0) * (lf["prix_unitaire"] or 0)
        taux = lf["tva_taux"] or 0

        # Par défaut compte 706 (prestations de services)
        if "706" not in produits:
            produits["706"] = 0
        produits["706"] += ht

        if taux > 0:
            tva_key = str(int(taux))
            if tva_key not in tva_par_taux:
                tva_par_taux[tva_key] = 0
            tva_par_taux[tva_key] += ht * taux / 100

    for compte, montant in produits.items():
        if montant > 0:
            ecriture_lignes.append({
                "compte": compte,
                "debit": 0,
                "credit": round(montant, 2),
                "libelle": f"Ventes — Facture {fact['numero']}",
            })

    for taux_str, montant in tva_par_taux.items():
        if montant > 0:
            ecriture_lignes.append({
                "compte": "4457",
                "debit": 0,
                "credit": round(montant, 2),
                "libelle": f"TVA collectée {taux_str}%",
            })

    eid = saisir_ecriture(
        fact["exercice_id"],
        "VTE",
        fact["date"],
        f"Facture {fact['numero']} — {fact.get('client_nom', 'Client')}",
        ecriture_lignes,
        piece=fact["numero"],
        reference=fact["numero"],
        conn=conn,
    )

    conn.execute(
        "UPDATE factures SET ecriture_id = ?, statut = 'envoyee' WHERE id = ?",
        (eid, facture_id),
    )

    if doit_fermer:
        conn.commit()
        conn.close()

    from .audit import log_action
    log_action("facture", facture_id, "generation_ecriture",
               {"ecriture_id": eid, "facture": fact["numero"]})
    return eid


def changer_statut(
    facture_id: int,
    statut: str,
    conn: Optional[sqlite3.Connection] = None,
):
    """Change le statut d'une facture."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    ancien = conn.execute("SELECT statut FROM factures WHERE id = ?", (facture_id,)).fetchone()
    ancien_statut = ancien["statut"] if ancien else None

    conn.execute(
        "UPDATE factures SET statut = ? WHERE id = ?",
        (statut.lower(), facture_id),
    )

    if doit_fermer:
        conn.commit()
        conn.close()

    from .audit import log_action
    log_action("facture", facture_id, "changement_statut",
               {"ancien": ancien_statut, "nouveau": statut.lower()})


def statistiques_factures(exercice_id: int, conn: Optional[sqlite3.Connection] = None) -> dict:
    """Statistiques : CA, nombre par statut, etc."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    stats = conn.execute(
        """SELECT statut, COUNT(*) as nb, SUM(total_ttc) as total
           FROM factures WHERE exercice_id = ?
           GROUP BY statut""",
        (exercice_id,),
    ).fetchall()

    if doit_fermer:
        conn.close()
    return {r["statut"]: {"nb": r["nb"], "total": r["total"] or 0} for r in stats}


def balance_agee(exercice_id: int, conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    """Balance âgée des créances clients."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    factures = conn.execute(
        """SELECT client_nom, date, echeance, total_ttc, statut
           FROM factures WHERE exercice_id = ? AND type = 'facture'
           AND statut NOT IN ('payee', 'annulee')
           ORDER BY client_nom, date""",
        (exercice_id,),
    ).fetchall()

    today = date.today()
    clients = {}
    for f in factures:
        nom = f["client_nom"] or "Client divers"
        if nom not in clients:
            clients[nom] = {"total": 0, "moins_30": 0, "30_60": 0, "plus_60": 0}

        montant = f["total_ttc"] or 0
        clients[nom]["total"] += montant

        # Déterminer l'âge
        ref_date = f["echeance"] or f["date"]
        try:
            d = datetime.strptime(ref_date, "%Y-%m-%d").date()
            age = (today - d).days
        except (ValueError, TypeError):
            age = 0

        if age <= 30:
            clients[nom]["moins_30"] += montant
        elif age <= 60:
            clients[nom]["30_60"] += montant
        else:
            clients[nom]["plus_60"] += montant

    if doit_fermer:
        conn.close()

    result = []
    for nom, montants in sorted(clients.items()):
        result.append({
            "client": nom,
            **{k: round(v, 2) for k, v in montants.items()},
        })
    return result
