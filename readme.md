# Agent Comptable — Boîte à outils PCG

Module Python de tenue comptable en partie double, conforme au Plan Comptable Général français.

## Structure

```
comptable/
├── __init__.py          # Package
├── plan_comptable.py    # Plan comptable PCG (~80 comptes, recherche)
├── db.py                # Schéma SQLite (écritures, lignes, exercices, auxiliaires)
├── ecritures.py         # Saisie d'écritures en partie double
├── balance.py           # Balance générale, compte de résultat, bilan synthétique
├── grand_livre.py       # Grand-livre par compte avec solde progressif
├── exercices.py         # Gestion des exercices comptables
├── export_fec.py        # Export FEC (format réglementaire DGFiP)
└── cli.py               # Interface en ligne de commande
demo.py                  # Script de démonstration complet
```

## Démarrage rapide

```bash
# 1. Initialiser la base
python -m comptable.cli init

# 2. Créer un exercice
python -m comptable.cli exercice-create "2025" 2025-01-01 2025-12-31

# 3. Saisir une écriture (interactif)
python -m comptable.cli ecriture-add

# 4. Consulter la balance
python -m comptable.cli balance

# 5. Compte de résultat
python -m comptable.cli resultat

# 6. Bilan synthétique
python -m comptable.cli bilan

# 7. Grand-livre d'un compte
python -m comptable.cli grand-livre 512

# 8. Export FEC
python -m comptable.cli fec fec_2025.txt --siren 123456789

# 9. Rechercher un compte
python -m comptable.cli recherche TVA
```

## Démonstration

```bash
python demo.py    # Crée un exercice, saisit 7 écritures, affiche tous les états
```

## API Python

```python
from comptable.db import init_db
from comptable.exercices import creer_exercice
from comptable.ecritures import saisir_ecriture
from comptable.balance import balance_generale, compte_resultat, bilan_synthetique
from comptable.grand_livre import grand_livre_compte
from comptable.export_fec import exporter_fec

init_db()
ex_id = creer_exercice("2025", "2025-01-01", "2025-12-31")
saisir_ecriture(ex_id, "BQ", "2025-01-15", "Apport capital",
    [{"compte": "512", "debit": 10000}, {"compte": "101", "credit": 10000}])
```

## Fonctionnalités couvertes

| Fonction | Module |
|---|---|
| Plan comptable (80+ comptes) | `plan_comptable.py` |
| Saisie en partie double | `ecritures.py` |
| Journaux (OD, ACH, VTE, BQ, CAISSE, ANOUV, CLOT) | `ecritures.py` |
| Balance générale | `balance.py` |
| Compte de résultat (charges/produits) | `balance.py` |
| Bilan synthétique actif/passif | `balance.py` |
| Grand-livre avec solde progressif | `grand_livre.py` |
| Export FEC réglementaire | `export_fec.py` |
| Comptes auxiliaires (clients, fournisseurs) | `db.py` |
| Gestion multi-exercices | `exercices.py` |
| CLI complète | `cli.py` |

## À venir (extensible)

- Rapprochement bancaire
- Déclarations TVA (CA3/CA12)
- Liasse fiscale
- Import CSV d'écritures
- Tableaux de bord et ratios
- Interface web légère
