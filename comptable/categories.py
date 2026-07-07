"""
Catégorisation automatique des lignes de relevé bancaire.
Stdlib uniquement. Pattern conn optionnel + doit_fermer.

Table : regles_categorisation.
"""

import csv
from collections import Counter
from typing import Optional

from comptable.db import get_db


# ── CRUD règles ────────────────────────────────────────────────────

# Règles pré-définies
_REGLES_BASE = [
    ("613", "loyer", "libelle"),
    ("606", "edf", "libelle"),
    ("606", "electricite", "libelle"),
    ("606", "engie", "libelle"),
    ("606", "gaz", "libelle"),
    ("606", "eau", "libelle"),
    ("626", "orange", "libelle"),
    ("626", "free", "libelle"),
    ("626", "bouygues", "libelle"),
    ("626", "telephone", "libelle"),
    ("626", "internet", "libelle"),
    ("606", "carburant", "libelle"),
    ("606", "essence", "libelle"),
    ("606", "diesel", "libelle"),
    ("606", "fournitures", "libelle"),
    ("607", "amazon", "libelle"),
    ("607", "fnac", "libelle"),
    ("607", "achat", "libelle"),
    ("616", "assurance", "libelle"),
    ("616", "mutuelle", "libelle"),
    ("623", "publicite", "libelle"),
    ("623", "pub", "libelle"),
    ("623", "facebook ads", "libelle"),
    ("623", "google ads", "libelle"),
    ("622", "honoraires", "libelle"),
    ("622", "comptable", "libelle"),
    ("622", "avocat", "libelle"),
    ("625", "restaurant", "libelle"),
    ("625", "resto", "libelle"),
    ("625", "repas", "libelle"),
    ("625", "hotel", "libelle"),
    ("625", "deplacement", "libelle"),
    ("627", "banque", "libelle"),
    ("627", "commission", "libelle"),
    ("445660", "tva", "libelle"),
    ("445710", "tva collectee", "libelle"),
    ("645", "urssaf", "libelle"),
    ("645", "securite sociale", "libelle"),
    ("645", "retraite", "libelle"),
    ("641", "salaire", "libelle"),
    ("641", "salaires", "libelle"),
    ("641", "paye", "libelle"),
    ("401", "fournisseur", "libelle"),
    ("706", "vente", "libelle"),
    ("706", "prestation", "libelle"),
    ("411", "client", "libelle"),
    ("512", "virement", "libelle"),
    ("512", "especes", "libelle"),
]


def ajouter_regle(
    compte_cible: str,
    mot_cle: str,
    champ: str = "libelle",
    priorite: int = 0,
) -> int:
    """Ajoute une règle de catégorisation. Retourne l'id."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO regles_categorisation
           (compte_cible, champ_recherche, mot_cle, priorite)
           VALUES (?,?,?,?)""",
        (compte_cible, champ, mot_cle, priorite),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def lister_regles() -> list[dict]:
    """Liste toutes les règles triées par priorité décroissante."""
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM regles_categorisation
           WHERE actif = 1 ORDER BY priorite DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def supprimer_regle(regle_id: int) -> dict:
    """Supprime une règle."""
    conn = get_db()
    conn.execute("DELETE FROM regles_categorisation WHERE id = ?", (regle_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


def importer_regles_csv(chemin_fichier: str) -> dict:
    """Importe des règles depuis un CSV (compte_cible,mot_cle,priorite)."""
    conn = get_db()
    nb = 0
    with open(chemin_fichier, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)  # skip header
        for row in reader:
            if len(row) < 2:
                continue
            compte = row[0].strip()
            mot_cle = row[1].strip()
            priorite = int(row[2].strip()) if len(row) > 2 and row[2].strip() else 0
            conn.execute(
                """INSERT INTO regles_categorisation
                   (compte_cible, mot_cle, priorite)
                   VALUES (?,?,?)""",
                (compte, mot_cle, priorite),
            )
            nb += 1
    conn.commit()
    conn.close()
    return {"ok": True, "nb_importees": nb}


# ── Catégorisation ─────────────────────────────────────────────────

def categoriser_ligne(libelle: str, montant_signe: float) -> Optional[dict]:
    """Applique les règles pour déterminer le compte d'une ligne.
    Retourne {compte, confiance, regle_id} ou None.
    """
    if not libelle:
        return None

    regles = lister_regles()
    libelle_lower = libelle.lower()

    for r in regles:
        mot = r["mot_cle"].lower()
        champ = r.get("champ_recherche", "libelle")

        if champ == "libelle" and mot in libelle_lower:
            return {
                "compte": r["compte_cible"],
                "confiance": 0.8,
                "regle_id": r["id"],
            }

    # Aucune règle trouvée
    return None


def categoriser_releve(releve_id: int) -> dict:
    """Catégorise toutes les lignes non catégorisées d'un relevé.
    Met à jour compte_suggere. Retourne stats.
    """
    conn = get_db()
    lignes = conn.execute(
        """SELECT id, description, montant
           FROM lignes_releve
           WHERE releve_id = ? AND compte_suggere IS NULL""",
        (releve_id,),
    ).fetchall()

    nb_categorisees = 0
    nb_restantes = 0
    details = []

    for ligne in lignes:
        result = categoriser_ligne(ligne["description"], ligne["montant"])
        if result:
            conn.execute(
                "UPDATE lignes_releve SET compte_suggere = ? WHERE id = ?",
                (result["compte"], ligne["id"]),
            )
            nb_categorisees += 1
            details.append({
                "ligne_id": ligne["id"],
                "libelle": ligne["description"],
                "compte_suggere": result["compte"],
                "confiance": result["confiance"],
            })
        else:
            nb_restantes += 1

    conn.commit()
    conn.close()
    return {
        "nb_categorisees": nb_categorisees,
        "nb_restantes": nb_restantes,
        "details": details,
    }


def suggerer_regles(exercice_id: int) -> list[dict]:
    """Analyse les écritures existantes pour proposer des règles.
    Retourne les paires (mot_frequent, compte) les plus courantes.
    """
    conn = get_db()
    # Récupérer les libellés de lignes d'écriture avec leur compte
    rows = conn.execute(
        """SELECT le.compte, le.libelle
           FROM lignes_ecriture le
           JOIN ecritures e ON e.id = le.ecriture_id
           WHERE e.exercice_id = ? AND le.libelle IS NOT NULL AND le.libelle != ''
           ORDER BY le.compte""",
        (exercice_id,),
    ).fetchall()

    # Extraire des mots fréquents par compte
    comptes_mots = {}
    import re
    for row in rows:
        compte = row["compte"]
        libelle = row["libelle"].lower()
        # Tokeniser : mots de 3+ caractères
        mots = set(re.findall(r"\b[a-z]{3,}\b", libelle))
        if compte not in comptes_mots:
            comptes_mots[compte] = Counter()
        comptes_mots[compte].update(mots)

    # Pour chaque compte, trouver les mots les plus fréquents
    suggestions = []
    for compte, mots_counter in comptes_mots.items():
        for mot, occ in mots_counter.most_common(5):
            if occ >= 2:  # Au moins 2 occurrences
                suggestions.append({
                    "mot_cle": mot,
                    "compte": compte,
                    "occurrences": occ,
                })

    # Trier par occurrences décroissantes
    suggestions.sort(key=lambda x: x["occurrences"], reverse=True)

    conn.close()
    return suggestions[:30]  # Top 30


def regles_predefinies() -> list[dict]:
    """Retourne les règles de base pré-définies."""
    return [
        {"compte_cible": r[0], "mot_cle": r[1], "champ": r[2]}
        for r in _REGLES_BASE
    ]
