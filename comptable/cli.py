"""
Interface en ligne de commande de l'agent comptable.

Usage :
  python -m comptable.cli init                    # Initialise la base
  python -m comptable.cli exercice create ...     # Crée un exercice
  python -m comptable.cli ecriture add ...        # Saisit une écriture
  python -m comptable.cli balance [--classe N]    # Affiche la balance
  python -m comptable.cli grand-livre COMPTE      # Grand-livre d'un compte
  python -m comptable.cli resultat                # Compte de résultat
  python -m comptable.cli bilan                   # Bilan synthétique
  python -m comptable.cli fec FICHIER             # Export FEC
"""

import argparse
import sys
from datetime import date

from .db import get_db, init_db
from .exercices import creer_exercice, lister_exercices, exercice_actif
from .ecritures import saisir_ecriture, ecritures_journal, supprimer_ecriture, JOURNAUX
from .balance import balance_generale, balance_par_classe, compte_resultat, bilan_synthetique
from .grand_livre import grand_livre_compte, grand_livre
from .export_fec import exporter_fec
from .plan_comptable import rechercher_compte, comptes_par_classe, CLASSES


def cmd_init(_args):
    """Initialise la base de données."""
    init_db()
    print("✅ Base de données initialisée (comptabilite.db)")


def cmd_exercice_create(args):
    """Crée un exercice."""
    eid = creer_exercice(args.libelle, args.debut, args.fin)
    print(f"✅ Exercice créé (id={eid}) : {args.libelle} du {args.debut} au {args.fin}")


def cmd_exercice_list(_args):
    """Liste les exercices."""
    exercices = lister_exercices()
    if not exercices:
        print("Aucun exercice.")
        return
    for e in exercices:
        status = "🔒 Clôturé" if e["cloture"] else "📂 Ouvert"
        print(f"  [{e['id']}] {e['libelle']} — {e['date_debut']} → {e['date_fin']}  {status}")


def cmd_ecriture_add(args):
    """Saisit une écriture interactive."""
    exercice = exercice_actif()
    if not exercice and not args.exercice:
        print("❌ Aucun exercice actif. Créez-en un ou passez --exercice ID.")
        return
    ex_id = args.exercice or exercice["id"]

    print(f"📝 Nouvelle écriture — exercice: {exercice['libelle'] if not args.exercice else f'id={ex_id}'}")
    journal = input(f"  Journal [{', '.join(JOURNAUX)}] (défaut: OD) : ").strip().upper() or "OD"
    date_str = input(f"  Date [AAAA-MM-JJ] (défaut: {date.today()}) : ").strip() or str(date.today())
    libelle = input("  Libellé : ").strip()
    piece = input("  Pièce (optionnel) : ").strip() or None
    ref = input("  Référence (optionnel) : ").strip() or None

    lignes = []
    print("  Lignes (compte, débit ou crédit). Tapez 'fin' pour terminer.")
    while True:
        compte = input("    Compte : ").strip()
        if compte.lower() == "fin":
            break
        montant = input("    Montant : ").strip()
        sens = input("    Sens [D/C] (défaut: D) : ").strip().upper() or "D"
        ll = input("    Libellé ligne (optionnel) : ").strip() or None

        debit = float(montant) if sens == "D" else 0
        credit = float(montant) if sens == "C" else 0
        lignes.append({"compte": compte, "debit": debit, "credit": credit, "libelle": ll})

    try:
        eid = saisir_ecriture(ex_id, journal, date_str, libelle, lignes, piece, ref)
        print(f"✅ Écriture enregistrée (id={eid})")
    except Exception as err:
        print(f"❌ Erreur : {err}")


def cmd_balance(args):
    """Affiche la balance."""
    exercice = exercice_actif()
    if not exercice:
        print("❌ Aucun exercice actif.")
        return

    if args.classe:
        par_classe = balance_par_classe(exercice["id"])
        for classe, lignes in par_classe.items():
            if args.classe and classe != args.classe:
                continue
            nom = CLASSES.get(classe, f"Classe {classe}")
            print(f"\n── {classe} — {nom} ──")
            for l in lignes:
                print(f"  {l['compte']:6s}  D={l['total_debit']:>10.2f}  C={l['total_credit']:>10.2f}  "
                      f"Solde={'D' if l['solde_debit'] else 'C'} {max(l['solde_debit'], l['solde_credit']):>10.2f}")
    else:
        balance = balance_generale(exercice["id"])
        total_db = sum(l["total_debit"] for l in balance)
        total_cr = sum(l["total_credit"] for l in balance)
        print(f"\n📊 Balance — Exercice : {exercice['libelle']}")
        for l in balance:
            print(f"  {l['compte']:6s}  D={l['total_debit']:>10.2f}  C={l['total_credit']:>10.2f}  "
                  f"Solde={'D' if l['solde_debit'] else 'C'} {max(l['solde_debit'], l['solde_credit']):>10.2f}")
        print(f"  {'─'*60}")
        print(f"  TOTAL  D={total_db:>10.2f}  C={total_cr:>10.2f}")


def cmd_resultat(args):
    """Affiche le compte de résultat."""
    exercice = exercice_actif()
    if not exercice:
        print("❌ Aucun exercice actif.")
        return

    cr = compte_resultat(exercice["id"])
    print(f"\n📈 Compte de résultat — {exercice['libelle']}")
    print(f"\n  CHARGES (classe 6) :")
    for c in cr["charges"]:
        print(f"    {c['compte']:6s}  {c['solde_debit']:>10.2f}")
    print(f"  Total charges : {cr['total_charges']:>10.2f}")

    print(f"\n  PRODUITS (classe 7) :")
    for p in cr["produits"]:
        print(f"    {p['compte']:6s}  {p['solde_credit']:>10.2f}")
    print(f"  Total produits : {cr['total_produits']:>10.2f}")

    sens = "✅ BÉNÉFICE" if cr["benefice"] else "❌ PERTE"
    print(f"\n  Résultat net : {cr['resultat_net']:>10.2f}  {sens}")


def cmd_bilan(args):
    """Affiche le bilan synthétique."""
    exercice = exercice_actif()
    if not exercice:
        print("❌ Aucun exercice actif.")
        return

    bilan = bilan_synthetique(exercice["id"])
    print(f"\n📋 Bilan — {exercice['libelle']}")
    print(f"\n  ACTIF :")
    for l in bilan["actif"]:
        lib = l.get("libelle", "")
        print(f"    {l['compte']:6s}  {l['solde_debit']:>10.2f}  {lib}")
    print(f"  Total actif : {bilan['total_actif']:>10.2f}")

    print(f"\n  PASSIF :")
    for l in bilan["passif"]:
        lib = l.get("libelle", "")
        print(f"    {l['compte']:6s}  {l['solde_credit']:>10.2f}  {lib}")
    print(f"  Total passif : {bilan['total_passif']:>10.2f}")

    eq = "✅" if bilan["equilibre"] else "⚠️ DÉSÉQUILIBRE"
    print(f"\n  Actif = Passif : {eq}")


def cmd_grand_livre(args):
    """Grand-livre d'un ou plusieurs comptes."""
    exercice = exercice_actif()
    if not exercice:
        print("❌ Aucun exercice actif.")
        return

    if args.compte:
        gl = grand_livre_compte(args.compte, exercice["id"])
        print(f"\n📖 Grand-livre — Compte {gl['compte']}")
        print(f"  Solde ouverture : {gl['solde_ouverture']:>10.2f}")
        for m in gl["mouvements"]:
            print(f"  {m['date']} {m['journal']:5s} {m['piece'] or '':8s} "
                  f"D={m['debit']:>10.2f} C={m['credit']:>10.2f} Solde={m['solde_cumul']:>10.2f}  {m['libelle']}")
        print(f"  {'─'*75}")
        print(f"  Total              D={gl['total_debit']:>10.2f} C={gl['total_credit']:>10.2f} "
              f"Solde final={gl['solde_final']:>10.2f}")
    else:
        gls = grand_livre(exercice["id"])
        for gl in gls:
            print(f"\n📖 Compte {gl['compte']}")
            for m in gl["mouvements"]:
                print(f"  {m['date']} {m['journal']:5s} D={m['debit']:>10.2f} C={m['credit']:>10.2f}  {m['libelle']}")
            print(f"  Solde final : {gl['solde_final']:>10.2f}")


def cmd_fec(args):
    """Export FEC."""
    exercice = exercice_actif()
    if not exercice:
        print("❌ Aucun exercice actif.")
        return

    nb = exporter_fec(exercice["id"], args.fichier, args.siren or "")
    print(f"✅ FEC exporté : {nb} lignes → {args.fichier}")


def cmd_recherche(args):
    """Recherche un compte dans le plan comptable."""
    comptes = rechercher_compte(args.q)
    if not comptes:
        print(f"Aucun compte trouvé pour '{args.q}'.")
        return
    for c in comptes:
        print(f"  {c.numero:6s}  {c.libelle}  (classe {c.classe}, sens {c.sens_naturel})")


def main():
    parser = argparse.ArgumentParser(description="Agent comptable — CLI")
    sub = parser.add_subparsers(dest="commande")

    # init
    sub.add_parser("init", help="Initialise la base de données")

    # exercice
    p_ex_create = sub.add_parser("exercice-create", help="Crée un exercice")
    p_ex_create.add_argument("libelle")
    p_ex_create.add_argument("debut", help="Date début (YYYY-MM-DD)")
    p_ex_create.add_argument("fin", help="Date fin (YYYY-MM-DD)")

    sub.add_parser("exercice-list", help="Liste les exercices")

    # ecriture
    p_ecr = sub.add_parser("ecriture-add", help="Saisit une écriture")
    p_ecr.add_argument("--exercice", type=int, help="ID de l'exercice")

    # balance
    p_bal = sub.add_parser("balance", help="Affiche la balance")
    p_bal.add_argument("--classe", type=int, choices=range(1, 9), help="Filtrer par classe")

    sub.add_parser("resultat", help="Affiche le compte de résultat")
    sub.add_parser("bilan", help="Affiche le bilan synthétique")

    # grand-livre
    p_gl = sub.add_parser("grand-livre", help="Grand-livre")
    p_gl.add_argument("compte", nargs="?", help="Numéro de compte (si absent, tous les comptes)")

    # fec
    p_fec = sub.add_parser("fec", help="Export FEC")
    p_fec.add_argument("fichier", help="Chemin du fichier de sortie")
    p_fec.add_argument("--siren", help="Numéro SIREN")

    # recherche
    p_rech = sub.add_parser("recherche", help="Recherche un compte PCG")
    p_rech.add_argument("q", help="Numéro ou libellé partiel")

    args = parser.parse_args()

    if args.commande is None:
        parser.print_help()
        return

    handlers = {
        "init": cmd_init,
        "exercice-create": cmd_exercice_create,
        "exercice-list": cmd_exercice_list,
        "ecriture-add": cmd_ecriture_add,
        "balance": cmd_balance,
        "resultat": cmd_resultat,
        "bilan": cmd_bilan,
        "grand-livre": cmd_grand_livre,
        "fec": cmd_fec,
        "recherche": cmd_recherche,
    }

    handler = handlers.get(args.commande)
    if handler:
        handler(args)


if __name__ == "__main__":
    main()
