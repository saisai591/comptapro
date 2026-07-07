"""
Banque : import CSV, rapprochement bancaire, état de rapprochement.
"""

import csv
import io
import os
import sqlite3
from typing import Optional

from .db import get_db


def importer_csv_text(
    exercice_id: int,
    csv_content: str,
    compte_bancaire: str = "512",
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Importe un CSV depuis une chaîne de caractères (sans créer de fichier temporaire)."""
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8-sig")
    try:
        tmp.write(csv_content)
        tmp.close()
        return importer_csv(exercice_id, compte_bancaire, tmp.name, conn)
    finally:
        import os
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def importer_csv(
    exercice_id: int,
    compte_bancaire: str,
    chemin_csv: str,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """
    Importe un relevé bancaire CSV.
    Détecte automatiquement les colonnes date, libellé, montant.
    Retourne le nombre de lignes importées.
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    with open(chemin_csv, "r", encoding="utf-8-sig") as f:
        content = f.read()

    # Détecter le délimiteur
    delimiter = "\t" if "\t" in content.split("\n")[0] else ","
    if ";" in content.split("\n")[0]:
        delimiter = ";"

    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    headers = reader.fieldnames or []

    # Auto-détection des colonnes
    col_date = _detect_col(headers, ["date", "date opération", "date_ope", "date valeur"])
    col_lib = _detect_col(headers, ["libellé", "libelle", "description", "intitulé", "objet", "désignation"])
    col_montant = _detect_col(headers, ["montant", "débit", "crédit", "debit", "credit"])
    col_ref = _detect_col(headers, ["référence", "reference", "ref", "n°", "numéro"])

    # Créer le relevé
    cur = conn.execute(
        "INSERT INTO releves_bancaires (exercice_id, compte_bancaire, fichier_original) VALUES (?,?,?)",
        (exercice_id, compte_bancaire, os.path.basename(chemin_csv)),
    )
    releve_id = cur.lastrowid
    nb = 0

    for row in reader:
        date_str = row.get(col_date, "") if col_date else ""
        libelle = row.get(col_lib, "") if col_lib else ""
        ref = row.get(col_ref, "") if col_ref else ""

        # Montant : positif = crédit, négatif = débit
        montant = 0.0
        if col_montant:
            val = row.get(col_montant, "0").replace(",", ".").replace(" ", "").replace("€", "")
            try:
                montant = float(val) if val else 0.0
            except ValueError:
                montant = 0.0

        # Si colonnes séparées débit/crédit
        col_debit = _detect_col(headers, ["débit", "debit"])
        col_credit = _detect_col(headers, ["crédit", "credit"])
        if col_debit and col_credit and not montant:
            d = _parse_float(row.get(col_debit, "0"))
            c = _parse_float(row.get(col_credit, "0"))
            montant = c - d  # positif = crédit

        if not date_str or not libelle:
            continue

        conn.execute(
            "INSERT INTO lignes_releve (releve_id, date, description, reference, montant) VALUES (?,?,?,?,?)",
            (releve_id, date_str.strip(), libelle.strip(), ref.strip(), montant),
        )
        nb += 1

    if doit_fermer:
        conn.commit()
        conn.close()
    return nb


def _detect_col(headers: list[str], candidates: list[str]) -> Optional[str]:
    """Détecte une colonne par son nom (insensible à la casse)."""
    for c in candidates:
        for h in headers:
            if c.lower() in h.lower():
                return h
    return None


def _parse_float(val: str) -> float:
    try:
        return float(val.replace(",", ".").replace(" ", "").replace("€", "") or "0")
    except (ValueError, AttributeError):
        return 0.0


def lister_releves(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Liste les relevés importés avec compteurs."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    rows = conn.execute(
        "SELECT * FROM releves_bancaires WHERE exercice_id = ? ORDER BY date_import DESC",
        (exercice_id,),
    ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        nb_lignes = conn.execute(
            "SELECT COUNT(*) as c FROM lignes_releve WHERE releve_id = ?", (r["id"],)
        ).fetchone()["c"]
        nb_rapp = conn.execute(
            "SELECT COUNT(*) as c FROM lignes_releve WHERE releve_id = ? AND rapproche = 1", (r["id"],)
        ).fetchone()["c"]
        d["nb_lignes"] = nb_lignes
        d["nb_rapprochees"] = nb_rapp
        result.append(d)

    if doit_fermer:
        conn.close()
    return result


def lignes_releve(releve_id: int, conn: Optional[sqlite3.Connection] = None) -> dict:
    """Retourne le détail d'un relevé avec ses lignes."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    releve = conn.execute(
        "SELECT * FROM releves_bancaires WHERE id = ?", (releve_id,)
    ).fetchone()

    if not releve:
        if doit_fermer:
            conn.close()
        return {"error": "Relevé introuvable"}

    lignes = conn.execute(
        "SELECT * FROM lignes_releve WHERE releve_id = ? ORDER BY date",
        (releve_id,),
    ).fetchall()

    result = dict(releve)
    result["lignes"] = [dict(l) for l in lignes]
    result["nb_rapprochees"] = sum(1 for l in result["lignes"] if l["rapproche"])

    if doit_fermer:
        conn.close()
    return result


def suggerer_compte(ligne_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[str]:
    """
    Suggère un compte comptable pour une ligne de relevé bancaire.
    Heuristique simple basée sur des mots-clés dans le libellé.
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    ligne = conn.execute("SELECT * FROM lignes_releve WHERE id = ?", (ligne_id,)).fetchone()
    if not ligne:
        if doit_fermer:
            conn.close()
        return None

    desc = (ligne["description"] or "").lower()
    mapping = {
        "salaire": "641", "loyer": "613", "electricité": "606", "edf": "606",
        "assurance": "616", "honoraire": "622", "téléphone": "626", "internet": "626",
        "fournisseur": "401", "client": "411", "urssaf": "431", "tva": "445",
        "impôt": "635", "taxe": "635", "banque": "627", "frais": "627",
        "retrait": "530", "virement": "512", "prélèvement": "512",
        "carte": "512", "chèque": "512", "espèces": "530",
    }
    for mot, compte in mapping.items():
        if mot in desc:
            if doit_fermer:
                conn.close()
            return compte

    if doit_fermer:
        conn.close()
    return "467"  # compte fourre-tout par défaut


def rapprocher(ligne_id: int, ecriture_id: int, conn: Optional[sqlite3.Connection] = None):
    """Rapproche une ligne de relevé avec une écriture."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    conn.execute(
        "UPDATE lignes_releve SET ecriture_id = ?, rapproche = 1 WHERE id = ?",
        (ecriture_id, ligne_id),
    )

    if doit_fermer:
        conn.commit()
        conn.close()


def etat_rapprochement(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """État de rapprochement : pointé vs non pointé."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    pointe = conn.execute(
        """SELECT SUM(montant) as total FROM lignes_releve lr
           JOIN releves_bancaires rb ON rb.id = lr.releve_id
           WHERE rb.exercice_id = ? AND lr.rapproche = 1""",
        (exercice_id,),
    ).fetchone()

    non_pointe = conn.execute(
        """SELECT SUM(montant) as total FROM lignes_releve lr
           JOIN releves_bancaires rb ON rb.id = lr.releve_id
           WHERE rb.exercice_id = ? AND lr.rapproche = 0""",
        (exercice_id,),
    ).fetchone()

    if doit_fermer:
        conn.close()

    return {
        "pointe": round(pointe["total"] or 0, 2),
        "non_pointe": round(non_pointe["total"] or 0, 2),
    }


def lignes_non_rapprochees(exercice_id: int, conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    """Liste les lignes non rapprochées d'un exercice."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    rows = conn.execute(
        """SELECT lr.*, rb.compte_bancaire FROM lignes_releve lr
           JOIN releves_bancaires rb ON rb.id = lr.releve_id
           WHERE rb.exercice_id = ? AND lr.rapproche = 0
           ORDER BY lr.date""",
        (exercice_id,),
    ).fetchall()

    if doit_fermer:
        conn.close()
    return [dict(r) for r in rows]


def auto_match_rapprochement(
    exercice_id: int,
    tolerance_jours: int = 5,
    tolerance_montant: float = 0.05,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """
    Auto-rapprochement : cherche des correspondances entre lignes de relevé
    non rapprochées et écritures bancaires (journal BQ) par date ± tolerance
    et montant ± tolerance.
    Retourne {nb_matches, matches: [{ligne_id, ecriture_id, montant, date}]}
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    # Lignes non rapprochées
    lignes = conn.execute(
        """SELECT lr.* FROM lignes_releve lr
           JOIN releves_bancaires rb ON rb.id = lr.releve_id
           WHERE rb.exercice_id = ? AND lr.rapproche = 0""",
        (exercice_id,),
    ).fetchall()

    # Écritures bancaires
    ecritures = conn.execute(
        """SELECT e.id, e.date, l.debit, l.credit, e.libelle
           FROM ecritures e
           JOIN lignes_ecriture l ON l.ecriture_id = e.id
           WHERE e.exercice_id = ? AND e.journal = 'BQ' AND l.compte LIKE '5%'""",
        (exercice_id,),
    ).fetchall()

    matches = []
    nb_match = 0
    for ligne in lignes:
        if ligne["rapproche"]:
            continue
        lm = ligne["montant"]
        ld = ligne["date"]
        best = None
        best_score = 999999
        for e in ecritures:
            em = e["debit"] - e["credit"]
            if abs(lm - em) > tolerance_montant:
                continue
            try:
                from datetime import datetime
                d1 = datetime.strptime(ld, "%Y-%m-%d")
                d2 = datetime.strptime(e["date"], "%Y-%m-%d")
                diff = abs((d1 - d2).days)
            except (ValueError, TypeError):
                diff = 999
            if diff > tolerance_jours:
                continue
            score = abs(lm - em) + diff * 0.01
            if score < best_score:
                best_score = score
                best = e
        if best:
            conn.execute(
                "UPDATE lignes_releve SET ecriture_id = ?, rapproche = 1 WHERE id = ?",
                (best["id"], ligne["id"]),
            )
            matches.append({
                "ligne_id": ligne["id"],
                "ecriture_id": best["id"],
                "montant": lm,
                "date": ld,
                "libelle_ecriture": best["libelle"],
            })
            nb_match += 1

    if doit_fermer:
        conn.commit()
        conn.close()
    return {"nb_matches": nb_match, "matches": matches}
