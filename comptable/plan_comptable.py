"""
Plan Comptable Général (PCG) français — conforme au règlement ANC 2014-03.

Fournit la liste des comptes, la recherche par numéro/libellé,
et la hiérarchie des classes.
"""

from dataclasses import dataclass, field
from typing import Optional

# ── Classes de comptes ──────────────────────────────────────────────
CLASSES = {
    1: "Comptes de capitaux",
    2: "Comptes d'immobilisations",
    3: "Comptes de stocks et en-cours",
    4: "Comptes de tiers",
    5: "Comptes financiers",
    6: "Comptes de charges",
    7: "Comptes de produits",
    8: "Comptes spéciaux",
}


@dataclass
class Compte:
    numero: str
    libelle: str
    classe: int
    sens: str  # "D" pour débit normal, "C" pour crédit normal
    actif: bool = True  # apparaît au bilan
    charge: bool = False
    produit: bool = False

    @property
    def est_collectif(self) -> bool:
        return len(self.numero) <= 2

    @property
    def sens_naturel(self) -> str:
        return "Débit" if self.sens == "D" else "Crédit"


# ── Plan de comptes (extrait pratique) ──────────────────────────────
PLAN_COMPTABLE: dict[str, Compte] = {
    # ── Classe 1 : Capitaux ──
    "101": Compte("101", "Capital", 1, "C"),
    "106": Compte("106", "Réserves", 1, "C"),
    "110": Compte("110", "Report à nouveau (solde créditeur)", 1, "C"),
    "119": Compte("119", "Report à nouveau (solde débiteur)", 1, "D"),
    "120": Compte("120", "Résultat de l'exercice (bénéfice)", 1, "C"),
    "129": Compte("129", "Résultat de l'exercice (perte)", 1, "D"),
    "164": Compte("164", "Emprunts auprès des établissements de crédit", 1, "C"),
    "166": Compte("166", "Autres emprunts et dettes assimilées", 1, "C"),
    # ── Classe 2 : Immobilisations ──
    "205": Compte("205", "Concessions, brevets, licences, logiciels", 2, "D"),
    "211": Compte("211", "Terrains", 2, "D"),
    "213": Compte("213", "Constructions", 2, "D"),
    "215": Compte("215", "Installations techniques, matériel et outillage", 2, "D"),
    "218": Compte("218", "Autres immobilisations corporelles", 2, "D"),
    "261": Compte("261", "Titres de participation", 2, "D"),
    "275": Compte("275", "Dépôts et cautionnements versés", 2, "D"),
    "280": Compte("280", "Amortissements des immobilisations incorporelles", 2, "C"),
    "281": Compte("281", "Amortissements des immobilisations corporelles", 2, "C"),
    # ── Classe 3 : Stocks ──
    "310": Compte("310", "Stocks de matières premières", 3, "D"),
    "350": Compte("350", "Stocks de produits intermédiaires", 3, "D"),
    "355": Compte("355", "Stocks de produits finis", 3, "D"),
    "370": Compte("370", "Stocks de marchandises", 3, "D"),
    # ── Classe 4 : Tiers ──
    "401": Compte("401", "Fournisseurs — dettes d'exploitation", 4, "C"),
    "404": Compte("404", "Fournisseurs d'immobilisations", 4, "C"),
    "408": Compte("408", "Fournisseurs — factures non parvenues", 4, "C"),
    "409": Compte("409", "Fournisseurs — avances et acomptes", 4, "D"),
    "411": Compte("411", "Clients — créances", 4, "D"),
    "416": Compte("416", "Clients douteux ou litigieux", 4, "D"),
    "418": Compte("418", "Clients — produits non encore facturés", 4, "D"),
    "419": Compte("419", "Clients — avances et acomptes reçus", 4, "C"),
    "421": Compte("421", "Personnel — rémunérations dues", 4, "C"),
    "431": Compte("431", "Sécurité sociale", 4, "C"),
    "437": Compte("437", "Autres organismes sociaux", 4, "C"),
    "438": Compte("438", "Charges sociales à payer", 4, "C"),
    "444": Compte("444", "État — impôts sur les bénéfices", 4, "C"),
    "445": Compte("445", "État — TVA", 4, "C"),
    "4455": Compte("4455", "TVA à décaisser", 4, "C"),
    "4456": Compte("4456", "TVA déductible", 4, "D"),
    "4457": Compte("4457", "TVA collectée", 4, "C"),
    "447": Compte("447", "Autres impôts, taxes et versements assimilés", 4, "C"),
    "455": Compte("455", "Associés — comptes courants", 4, "C"),
    "467": Compte("467", "Autres comptes débiteurs ou créditeurs", 4, "D"),
    "486": Compte("486", "Charges constatées d'avance", 4, "D"),
    "487": Compte("487", "Produits constatés d'avance", 4, "C"),
    # ── Classe 5 : Financiers ──
    "512": Compte("512", "Banque", 5, "D"),
    "514": Compte("514", "Chèques postaux", 5, "D"),
    "530": Compte("530", "Caisse", 5, "D"),
    # ── Classe 6 : Charges ──
    "601": Compte("601", "Achats de matières premières", 6, "D", charge=True),
    "604": Compte("604", "Achats d'études et prestations de services", 6, "D", charge=True),
    "606": Compte("606", "Achats non stockés de matières et fournitures", 6, "D", charge=True),
    "607": Compte("607", "Achats de marchandises", 6, "D", charge=True),
    "613": Compte("613", "Locations", 6, "D", charge=True),
    "615": Compte("615", "Entretien et réparations", 6, "D", charge=True),
    "616": Compte("616", "Primes d'assurance", 6, "D", charge=True),
    "618": Compte("618", "Divers services extérieurs", 6, "D", charge=True),
    "622": Compte("622", "Rémunérations d'intermédiaires et honoraires", 6, "D", charge=True),
    "623": Compte("623", "Publicité, publications, relations publiques", 6, "D", charge=True),
    "624": Compte("624", "Transports de biens et collectifs du personnel", 6, "D", charge=True),
    "625": Compte("625", "Déplacements, missions et réceptions", 6, "D", charge=True),
    "626": Compte("626", "Frais postaux et de télécommunications", 6, "D", charge=True),
    "627": Compte("627", "Services bancaires et assimilés", 6, "D", charge=True),
    "631": Compte("631", "Impôts, taxes et versements assimilés (administration)", 6, "D", charge=True),
    "641": Compte("641", "Rémunérations du personnel", 6, "D", charge=True),
    "645": Compte("645", "Charges de sécurité sociale et de prévoyance", 6, "D", charge=True),
    "661": Compte("661", "Charges d'intérêts", 6, "D", charge=True),
    "665": Compte("665", "Pertes de change sur créances et dettes", 6, "D", charge=True),
    "671": Compte("671", "Charges exceptionnelles sur opérations de gestion", 6, "D", charge=True),
    "675": Compte("675", "Valeurs comptables des éléments d'actif cédés", 6, "D", charge=True),
    "681": Compte("681", "Dotations aux amortissements et provisions — charges", 6, "D", charge=True),
    "686": Compte("686", "Dotations aux provisions financières", 6, "D", charge=True),
    "695": Compte("695", "Impôts sur les bénéfices", 6, "D", charge=True),
    # ── Classe 7 : Produits ──
    "701": Compte("701", "Ventes de produits finis", 7, "C", produit=True),
    "704": Compte("704", "Travaux", 7, "C", produit=True),
    "706": Compte("706", "Prestations de services", 7, "C", produit=True),
    "707": Compte("707", "Ventes de marchandises", 7, "C", produit=True),
    "708": Compte("708", "Produits des activités annexes", 7, "C", produit=True),
    "740": Compte("740", "Subventions d'exploitation", 7, "C", produit=True),
    "751": Compte("751", "Redevances pour concessions, brevets, licences", 7, "C", produit=True),
    "756": Compte("756", "Gains de change sur créances et dettes", 7, "C", produit=True),
    "764": Compte("764", "Revenus des valeurs mobilières de placement", 7, "C", produit=True),
    "766": Compte("766", "Produits nets sur cessions de VMP", 7, "C", produit=True),
    "771": Compte("771", "Produits exceptionnels sur opérations de gestion", 7, "C", produit=True),
    "775": Compte("775", "Produits des cessions d'éléments d'actif", 7, "C", produit=True),
    "791": Compte("791", "Transferts de charges d'exploitation", 7, "C", produit=True),
}


# ── Recherche ───────────────────────────────────────────────────────
def rechercher_compte(recherche: str) -> list[Compte]:
    """Recherche un compte par numéro ou libellé (partiel, insensible à la casse)."""
    q = recherche.lower().strip()
    resultats = []
    for numero, compte in PLAN_COMPTABLE.items():
        if q in numero or q in compte.libelle.lower():
            resultats.append(compte)
    return sorted(resultats, key=lambda c: int(c.numero))


def compte_par_numero(numero: str) -> Optional[Compte]:
    """Retourne le compte correspondant au numéro exact."""
    return PLAN_COMPTABLE.get(numero)


def comptes_par_classe(classe: int) -> list[Compte]:
    """Retourne tous les comptes d'une classe donnée (1 à 8)."""
    return sorted(
        [c for c in PLAN_COMPTABLE.values() if c.classe == classe],
        key=lambda c: int(c.numero),
    )


def tous_les_comptes() -> list[Compte]:
    """Retourne tous les comptes triés par numéro."""
    return sorted(PLAN_COMPTABLE.values(), key=lambda c: int(c.numero))
