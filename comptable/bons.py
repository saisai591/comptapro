"""
Bons de commande, bons de livraison, pro-forma.
Extension de la table factures avec champ sous_type.
"""

import sqlite3
from typing import Optional

from .db import get_db
from .facturation import creer_facture, generer_ecriture_facture


def creer_bon(
    exercice_id: int,
    type_facture: str,
    sous_type: str,
    date_str: str,
    client_nom: str,
    lignes: list[dict],
    echeance: Optional[str] = None,
    notes: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """
    Crée un bon (commande, livraison, pro-forma) sans générer d'écriture.
    sous_type : 'bon_commande', 'bon_livraison', 'pro_forma'
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    fid = creer_facture(
        exercice_id, type_facture, date_str, lignes,
        client_nom=client_nom, echeance=echeance, notes=notes,
        conn=conn,
    )

    conn.execute(
        "UPDATE factures SET sous_type = ? WHERE id = ?",
        (sous_type, fid),
    )
    conn.commit()

    if doit_fermer:
        conn.close()

    return fid


def lister_bons(
    exercice_id: int,
    sous_type: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Liste les bons filtrés par sous_type (None = tous les bons)."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    if sous_type:
        rows = conn.execute(
            "SELECT * FROM factures WHERE exercice_id = ? AND sous_type = ? ORDER BY date DESC",
            (exercice_id, sous_type),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM factures WHERE exercice_id = ? AND sous_type IS NOT NULL ORDER BY date DESC",
            (exercice_id,),
        ).fetchall()

    result = [dict(r) for r in rows]

    if doit_fermer:
        conn.close()

    return result


def convertir_bon_en_facture(
    bon_id: int,
    generer_ecriture: bool = True,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """
    Convertit un bon de commande ou pro-forma en vraie facture.
    Change sous_type=NULL, statut='envoyee', génère l'écriture si demandé.
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    bon = conn.execute("SELECT * FROM factures WHERE id = ?", (bon_id,)).fetchone()
    if not bon:
        raise ValueError(f"Bon {bon_id} introuvable")
    if bon["type"] != "facture":
        raise ValueError(
            f"L'ID {bon_id} n'est pas une facture (type={bon['type']})"
        )
    st = bon["sous_type"]
    if st not in ("bon_commande", "pro_forma"):
        raise ValueError(
            f"L'ID {bon_id} n'est pas un bon convertible (sous_type={st})"
        )

    conn.execute(
        "UPDATE factures SET sous_type = NULL, statut = 'envoyee' WHERE id = ?",
        (bon_id,),
    )
    conn.commit()

    if generer_ecriture:
        generer_ecriture_facture(bon_id, conn=conn)

    if doit_fermer:
        conn.close()

    return bon_id


def convertir_bon_en_livraison(
    bon_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Convertit un bon de commande en bon de livraison."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    bon = conn.execute("SELECT * FROM factures WHERE id = ?", (bon_id,)).fetchone()
    if not bon:
        raise ValueError(f"Bon {bon_id} introuvable")
    if bon["sous_type"] != "bon_commande":
        raise ValueError(
            f"L'ID {bon_id} n'est pas un bon de commande "
            f"(sous_type={bon['sous_type']})"
        )

    conn.execute(
        "UPDATE factures SET sous_type = 'bon_livraison' WHERE id = ?",
        (bon_id,),
    )
    conn.commit()

    if doit_fermer:
        conn.close()
