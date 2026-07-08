"""
Serveur HTTP — API JSON + SPA. Style Pennylane.
Routes : exercices, écritures, balance, factures,
banque (import CSV, rapprochement), dashboard (KPIs, TVA), paramètres.
"""

import json, logging, os, re, sys, tempfile, io
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# QR code generation (optional dependency)
try:
    import qrcode as _qrlib
    HAS_QR = True
except ImportError:
    HAS_QR = False

# Logging
logging.basicConfig(
    filename=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("compta")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comptable.db import init_db, get_db, DB_PATH
from comptable.exercices import creer_exercice, lister_exercices, exercice_actif
from comptable.ecritures import saisir_ecriture, ecritures_journal, JOURNAUX
from comptable.balance import balance_generale, compte_resultat, bilan_synthetique
from comptable.grand_livre import grand_livre_compte
from comptable.plan_comptable import rechercher_compte, tous_les_comptes, CLASSES
from comptable.facturation import (
    creer_facture, lister_factures, facture_detail,
    generer_ecriture_facture, changer_statut,
    statistiques_factures, balance_agee,
)
from comptable.banque import (
    importer_csv, suggerer_compte, rapprocher,
    etat_rapprochement, lignes_non_rapprochees,
    lister_releves, lignes_releve, auto_match_rapprochement,
)
from comptable.dashboard import (
    kpi_tresorerie, evolution_ca, tva_preview,
    top_clients, top_fournisseurs, resume_jour,
)
from comptable.relances import (
    creer_scenario, lister_scenarios, supprimer_scenario,
    executer_relances, historique_relances, resume_relances,
)
from comptable.budget import (
    definir_budget, importer_budget_csv, lister_budgets,
    comparaison_budget, resume_budgetaire,
)
from comptable.notes_frais import (
    creer_note, lister_notes, valider_note,
    generer_ecriture_note, stats_notes,
)
from comptable.audit import historique_entite, dernieres_actions
from comptable.email import (
    config_smtp, tester_connexion, envoyer_email,
    envoyer_facture_email, envoyer_relance_email, envoyer_relances_auto,
)
from comptable.lettrage import (
    creer_lettrage, ajouter_ligne_lettrage, lister_lettrages,
    detail_lettrage, supprimer_lettrage, suggerer_lettrage, comptes_lettrables,
)
from comptable.previsionnel import (
    ajouter_prevision, lister_previsions, supprimer_prevision,
    projection_tresorerie, runway, alertes_tresorerie,
)
from comptable.tva import (
    calculer_tva_periode, declaration_ca3, declaration_ca12,
    historique_tva, acomptes_tva,
)
from comptable.validation_achats import (
    ajouter_achat, lister_achats, valider_achat, rejeter_achat,
    generer_ecriture_achat, marquer_paye_manuel,
    stats_validations, export_paiements,
)
from comptable.abonnements import (
    creer_abonnement, lister_abonnements, desactiver_abonnement,
    executer_abonnements, prochains_abonnements, resume_abonnements,
)
from comptable.paie import importer_paie_csv, modele_paie
from comptable.bons import creer_bon, lister_bons, convertir_bon_en_facture, convertir_bon_en_livraison
from comptable.auto_match import auto_rapprocher, auto_rapprocher_factures, etat_rapprochement_auto
from comptable.cloture import verifications_cloture, cloturer_exercice, simuler_cloture, reouvrir_exercice
from comptable.immobilisations import (
    lister_immobilisations, ajouter_immobilisation,
    calculer_amortissements, generer_ecritures_amortissement,
    plan_amortissement, resume_immobilisations, ceder_immobilisation,
)
from comptable.emprunts import (
    lister_emprunts, ajouter_emprunt,
    generer_tableau_amortissement, tableau_amortissement,
    generer_ecriture_echeance, resume_emprunts, cloturer_emprunt,
)
from comptable.categories import (
    lister_regles, ajouter_regle, supprimer_regle,
    importer_regles_csv, categoriser_ligne, categoriser_releve,
    suggerer_regles, regles_predefinies,
)
# Auth not used in this version
from comptable.recherche import (
    rechercher_global, rechercher_ecritures, rechercher_factures,
    indexer,
)
from comptable.export_excel import (
    exporter_balance_csv, exporter_grand_livre_csv,
    exporter_ecritures_csv, exporter_journaux_csv,
    exporter_factures_csv, exporter_bilan_csv,
)
from comptable.pieces_jointes import (
    lister_pj, get_pj, get_pj_fichier, ajouter_pj,
    lier_pj, supprimer_pj, stats_pj,
    handle_upload, get_mobile_url, validate_mobile_token, generate_mobile_token,
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class ComptaHandler(SimpleHTTPRequestHandler):
    """Handler HTTP — API REST + fichiers statiques."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)
        self._current_user = None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        # ── Mobile Bridge upload page ──
        if path == "/mobile/upload" or path.startswith("/mobile/upload?"):
            token = qs.get("token", [""])[0]
            if not validate_mobile_token(token):
                self.send_response(403)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<h2>Lien expire ou invalide. Regenez un QR code depuis ComptaPro.</h2>".encode())
                return
            self.path = "/mobile-upload.html"
            return super().do_GET()

                # ── QR Code token + QR Code PNG ──
        if path == "/api/qrcode/token":
            public_url = os.environ.get("COMPTAPRO_PUBLIC_URL")
            if not public_url:
                host = self.headers.get("Host", "localhost:8080")
                if host.startswith("localhost") or host.startswith("127."):
                    lan = self._detect_lan_ip()
                    public_url = f"http://{lan}:8080" if lan else f"http://{host}"
                else:
                    public_url = f"http://{host}"
            token = generate_mobile_token(public_url)
            full_url = public_url + "/mobile/upload?token=" + token
            return self._json({"token": token, "url": full_url})

        if path == "/api/qrcode":
            data = qs.get("data", qs.get("url", [None]))[0]
            if not data:
                public_url = os.environ.get(
                    "COMPTAPRO_PUBLIC_URL",
                    f"http://{self.headers.get('Host', 'localhost:8080')}"
                )
                data = get_mobile_url(public_url)
            if HAS_QR:
                img = _qrlib.make(data)
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                png = buf.getvalue()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", len(png))
                self.end_headers()
                self.wfile.write(png)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(data.encode())
            return

        # ── Static / login page ──
        if path == "/login":
            self.path = "/login.html"
            return super().do_GET()

        # Exercices
        if path == "/api/exercices":
            return self._json(lister_exercices())

        # Recherche globale
        if path == "/api/search":
            q = qs.get("q", [""])[0]
            ex_id = int(qs.get("exercice_id", ["0"])[0]) or (exercice_actif() or {}).get("id")
            if not ex_id:
                return self._json({"results": []})
            return self._json(self._search_all(ex_id, q))

        # Plan comptable
        if path == "/api/plan-comptable":
            q = qs.get("q", [""])[0]
            if q:
                return self._json([self._compte_dict(c) for c in rechercher_compte(q)])
            return self._json([self._compte_dict(c) for c in tous_les_comptes()])

        # Balance
        if path == "/api/balance":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(balance_generale(ex_id))

        # Résultat
        if path == "/api/resultat":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(compte_resultat(ex_id))

        # Bilan
        if path == "/api/bilan":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(bilan_synthetique(ex_id))

        # Grand-livre
        if path == "/api/grand-livre":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            compte = qs.get("compte", [None])[0]
            if not compte:
                return self._json({"error": "Paramètre 'compte' requis"}, 400)
            return self._json(grand_livre_compte(compte, ex_id))

        # Écritures (liste)
        if path == "/api/ecritures":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            q = qs.get("q", [""])[0]
            ecritures = self._list_ecritures(ex_id, q)
            return self._json(ecritures)

        # Journaux
        if path == "/api/journaux":
            return self._json([{"code": k, "libelle": v} for k, v in JOURNAUX.items()])

        # Écritures (liste avec recherche et pagination)
        if path == "/api/ecritures":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            q = qs.get("q", [None])[0]
            limit = int(qs.get("limit", [200])[0])
            offset = int(qs.get("offset", [0])[0])
            return self._json(self._list_ecritures(ex_id, q or "", limit, offset))

        # ── Factures ──
        if path == "/api/factures":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            type_f = qs.get("type", [None])[0]
            statut = qs.get("statut", [None])[0]
            return self._json(lister_factures(ex_id, type_f, statut))

        if path.startswith("/api/factures/") and not path.endswith("/stats") and not path.endswith("/balance-agee"):
            parts = path.split("/")
            if len(parts) == 4 and parts[3].isdigit():
                fid = int(parts[3])
                detail = facture_detail(fid)
                if detail is None:
                    return self._json({"error": "Facture introuvable"}, 404)
                return self._json(detail)

        if path == "/api/factures/stats":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(statistiques_factures(ex_id))

        if path == "/api/factures/balance-agee":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(balance_agee(ex_id))

        # ── Banque ──
        if path == "/api/banque/releves":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            rid = qs.get("releve_id", [None])[0]
            if rid:
                # Détail d'un relevé
                from comptable.banque import lignes_releve, etat_rapprochement
                lignes = lignes_releve(int(rid))
                etat = etat_rapprochement(int(rid))
                return self._json({"lignes": lignes, "nb_rapprochees": etat.get("nb_lignes_pointees", 0)})
            return self._json(lister_releves(ex_id))

        # GET /api/banque/releves/:id
        if path.startswith("/api/banque/releves/") and path.count("/") == 4:
            try:
                rid = int(path.split("/")[3])
                from comptable.banque import lignes_releve, etat_rapprochement
                lignes = lignes_releve(rid)
                etat = etat_rapprochement(rid)
                # Adapte les noms de champs pour le frontend
                lignes_adaptees = []
                for l in lignes:
                    lignes_adaptees.append({
                        **l, "libelle": l.get("description", ""),
                    })
                return self._json({"lignes": lignes_adaptees, "nb_rapprochees": etat.get("nb_lignes_pointees", 0)})
            except (ValueError, IndexError):
                return self._json({"error": "ID relevé invalide"}, 400)

        if path == "/api/banque/non-rapprochees":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(lignes_non_rapprochees(ex_id))

        # ── Dashboard ──
        if path == "/api/dashboard/tresorerie":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(kpi_tresorerie(ex_id))

        if path == "/api/dashboard/evolution":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(evolution_ca(ex_id))

        if path == "/api/dashboard/tva":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            df = qs.get("date_fin", [None])[0]
            return self._json(tva_preview(ex_id, df))

        if path == "/api/dashboard/top":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            limite = int(qs.get("limite", [5])[0])
            clients = top_clients(ex_id, limite)
            # Adapte les clés pour le frontend (nom->client, total->ca)
            return self._json([{"client": c.get("nom", c.get("client", "?")), "ca": c.get("total", 0)} for c in clients])

        if path == "/api/dashboard/resume":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(resume_jour(ex_id))

        # Notifications
        if path == "/api/notifications":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(self._get_notifications(ex_id))

        # Export CSV
        if path == "/api/export/csv":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            typ = qs.get("type", ["ecritures"])[0]
            return self._export_csv(ex_id, typ)

        # ── Pieces jointes ──
        if path == "/api/pj":
            return self._json(lister_pj(
                categorie=qs.get("categorie", [None])[0],
                ecriture_id=int(qs.get("ecriture_id", [0])[0]) or None,
                facture_id=int(qs.get("facture_id", [0])[0]) or None,
                date_debut=qs.get("date_debut", [None])[0],
                date_fin=qs.get("date_fin", [None])[0],
                offset=int(qs.get("offset", [0])[0]),
                limit=int(qs.get("limit", [50])[0]),
            ))
        if path == "/api/pj/stats":
            return self._json(stats_pj())
        if path == "/api/pj/fichier":
            pj_id = int(qs.get("id", [0])[0])
            if not pj_id:
                return self._json({"error": "Parametre id requis"}, 400)
            f = get_pj_fichier(pj_id)
            if not f:
                return self._json({"error": "Piece introuvable"}, 404)
            data, mime, nom = f
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", len(data))
            self.send_header("Content-Disposition", f"inline; filename={nom}")
            self.send_header("Cache-Control", "max-age=86400")
            self.end_headers()
            self.wfile.write(data)
            return
        pi = re.match(r"^/api/pj/(\d+)$", path)
        if pi:
            pj = get_pj(int(pi.group(1)))
            if not pj:
                return self._json({"error": "Piece introuvable"}, 404)
            return self._json(pj)

        # Templates de facture
        if path == "/api/factures/templates":
            return self._json(self._get_templates())

        # ── Impression PDF (templates HTML imprimables) ──
        if path.endswith("/imprimer") and path.startswith("/api/factures/"):
            parts = path.split("/")
            if len(parts) == 5 and parts[3].isdigit():
                fid = int(parts[3])
                detail = facture_detail(fid)
                if detail is None:
                    return self._json({"error": "Facture introuvable"}, 404)
                from comptable.pdf_templates import template_facture, _param_entreprise
                conn = get_db()
                params = _param_entreprise(conn)
                html = template_facture(detail, detail.get("lignes", []), params)
                conn.close()
                self._html(html)
                return

        if path == "/api/balance/imprimer":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            from comptable.pdf_templates import template_balance, _param_entreprise
            conn = get_db()
            params = _param_entreprise(conn)
            ex = conn.execute("SELECT libelle FROM exercices WHERE id = ?", [ex_id]).fetchone()
            libelle = ex["libelle"] if ex else ""
            html = template_balance(balance_generale(ex_id), libelle, params)
            conn.close()
            self._html(html)
            return

        if path == "/api/bilan/imprimer":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            from comptable.pdf_templates import template_bilan, _param_entreprise
            conn = get_db()
            params = _param_entreprise(conn)
            ex = conn.execute("SELECT libelle FROM exercices WHERE id = ?", [ex_id]).fetchone()
            libelle = ex["libelle"] if ex else ""
            html = template_bilan(bilan_synthetique(ex_id), libelle, params)
            conn.close()
            self._html(html)
            return

        if path == "/api/grand-livre/imprimer":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            compte = qs.get("compte", [None])[0]
            if not compte:
                return self._json({"error": "Paramètre compte requis"}, 400)
            from comptable.pdf_templates import template_grand_livre, _param_entreprise
            conn = get_db()
            params = _param_entreprise(conn)
            ex = conn.execute("SELECT libelle FROM exercices WHERE id = ?", [ex_id]).fetchone()
            libelle = ex["libelle"] if ex else ""
            html = template_grand_livre(grand_livre_compte(compte, ex_id), libelle, params)
            conn.close()
            self._html(html)
            return

        # ── Resultat imprimer ──
        if path == "/api/resultat/imprimer":
            ex_id = self._exercice_id(qs)
            if ex_id is None: return
            from comptable.pdf_templates import template_resultat, _param_entreprise
            conn = get_db()
            params = _param_entreprise(conn)
            ex = conn.execute("SELECT libelle FROM exercices WHERE id = ?", [ex_id]).fetchone()
            libelle = ex["libelle"] if ex else ""
            html = template_resultat(compte_resultat(ex_id), libelle, params)
            conn.close()
            self._html(html)
            return

        # ── Budget imprimer ──
        if path == "/api/budget/imprimer":
            ex_id = self._exercice_id(qs)
            if ex_id is None: return
            from comptable.pdf_templates import template_budget, _param_entreprise
            from comptable.budget import comparaison_budget, resume_budgetaire
            conn = get_db()
            params = _param_entreprise(conn)
            ex = conn.execute("SELECT libelle FROM exercices WHERE id = ?", [ex_id]).fetchone()
            libelle = ex["libelle"] if ex else ""
            html = template_budget(comparaison_budget(ex_id), resume_budgetaire(ex_id), libelle, params)
            conn.close()
            self._html(html)
            return

        # ── Relances ──
        if path == "/api/relances/scenarios":
            return self._json(lister_scenarios())
        if path == "/api/relances/executer":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(executer_relances(ex_id))
        if path == "/api/relances/historique":
            fid = qs.get("facture_id", [None])[0]
            if fid:
                return self._json(historique_relances(int(fid)))
            return self._json([])
        if path == "/api/relances/resume":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(resume_relances(ex_id))

        # ── Budget ──
        if path == "/api/budget/liste":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            mois = int(qs.get("mois", [0])[0]) or None
            return self._json(lister_budgets(ex_id, mois))
        if path == "/api/budget/comparaison":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            mois = int(qs.get("mois", [0])[0]) or None
            return self._json(comparaison_budget(ex_id, mois))
        if path == "/api/budget/resume":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(resume_budgetaire(ex_id))

        # ── Notes de frais ──
        if path == "/api/notes-frais":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            statut = qs.get("statut", [None])[0]
            cat = qs.get("categorie", [None])[0]
            return self._json(lister_notes(ex_id, statut, cat))
        if path == "/api/notes-frais/stats":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(stats_notes(ex_id))

        # ── Paramètres ──
        if path == "/api/parametres":
            return self._json(self._get_parametres())

        # ── Audit ──
        if path == "/api/audit" and "entite_type" in qs:
            return self._json(historique_entite(qs["entite_type"][0], int(qs["entite_id"][0])))
        if path == "/api/audit/recent":
            return self._json(dernieres_actions(int(qs.get("limite", [20])[0])))

        # ── Email ──
        if path == "/api/email/config":
            try:
                return self._json(config_smtp())
            except Exception:
                return self._json({})
        if path == "/api/email/test":
            try:
                cfg = config_smtp()
                ok, msg = tester_connexion(cfg)
                return self._json({"ok": ok, "message": msg})
            except Exception as e:
                return self._json({"ok": False, "message": str(e)})

        # ── Lettrage ──
        if path == "/api/lettrage":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            lid = qs.get("id", [None])[0]
            if lid:
                return self._json(detail_lettrage(int(lid)))
            return self._json(lister_lettrages(ex_id))
        if path == "/api/lettrage/comptes":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(comptes_lettrables(ex_id))
        if path == "/api/lettrage/suggerer":
            compte = qs.get("compte", [None])[0]
            if not compte:
                return self._json({"error": "compte requis"}, 400)
            return self._json(suggerer_lettrage(compte))

        # ── Prévisionnel ──
        if path == "/api/previsionnel":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            mois = qs.get("mois", [None])[0]
            return self._json(lister_previsions(ex_id, int(mois) if mois else None))
        if path == "/api/previsionnel/projection":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(projection_tresorerie(ex_id))
        if path == "/api/previsionnel/runway":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(runway(ex_id))
        if path == "/api/previsionnel/alertes":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(alertes_tresorerie(ex_id))

        # ── TVA ──
        if path == "/api/tva/periode":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            debut = qs.get("debut", [None])[0]
            fin = qs.get("fin", [None])[0]
            if not debut or not fin:
                return self._json({"error": "debut et fin requis"}, 400)
            return self._json(calculer_tva_periode(ex_id, debut, fin))
        if path == "/api/tva/ca3":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            debut = qs.get("debut", [None])[0]
            fin = qs.get("fin", [None])[0]
            if not debut or not fin:
                return self._json({"error": "debut et fin requis"}, 400)
            return self._json(declaration_ca3(ex_id, debut, fin))
        if path == "/api/tva/historique":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(historique_tva(ex_id))
        if path == "/api/tva/acomptes":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(acomptes_tva(ex_id))

        # ── Validation Achats ──
        if path == "/api/achats":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            statut = qs.get("statut", [None])[0]
            return self._json(lister_achats(ex_id, statut))
        if path == "/api/achats/stats":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(stats_validations(ex_id))
        if path == "/api/achats/export-paiements":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(export_paiements(ex_id))

        # ── Abonnements ──
        if path == "/api/abonnements":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(lister_abonnements(ex_id))
        if path == "/api/abonnements/resume":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(resume_abonnements(ex_id))
        if path == "/api/abonnements/prochains":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            jours = int(qs.get("jours", [30])[0])
            return self._json(prochains_abonnements(ex_id, jours))
        if path == "/api/abonnements/executer":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(executer_abonnements(ex_id))

        # ── Recherche ──
        if path == "/api/recherche":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            q = qs.get("q", [""])[0]
            if not q:
                return self._json([])
            return self._json(rechercher_global(ex_id, q))

        # ── Export Excel/CSV ──
        if path == "/api/export/balance":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            fichier = qs.get("fichier", ["balance.csv"])[0]
            chemin = os.path.join(os.path.dirname(os.path.dirname(__file__)), fichier)
            nb = exporter_balance_csv(ex_id, chemin)
            return self._json({"ok": True, "fichier": chemin, "nb_lignes": nb})
        if path == "/api/export/ecritures":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            fichier = qs.get("fichier", ["ecritures.csv"])[0]
            chemin = os.path.join(os.path.dirname(os.path.dirname(__file__)), fichier)
            nb = exporter_ecritures_csv(ex_id, chemin)
            return self._json({"ok": True, "fichier": chemin, "nb_lignes": nb})
        if path == "/api/export/factures":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            fichier = qs.get("fichier", ["factures.csv"])[0]
            chemin = os.path.join(os.path.dirname(os.path.dirname(__file__)), fichier)
            nb = exporter_factures_csv(ex_id, chemin)
            return self._json({"ok": True, "fichier": chemin, "nb_lignes": nb})

        # ── Paie ──
        if path == "/api/paie/modele":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(modele_paie(ex_id))

        # ── Bons ──
        if path == "/api/bons":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            st = qs.get("sous_type", [None])[0]
            return self._json(lister_bons(ex_id, st))

        # ── Auto-match ──
        if path == "/api/banque/auto-match":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(auto_match_rapprochement(ex_id))
        if path == "/api/banque/etat-auto":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(etat_rapprochement_auto(ex_id))

        # ── Clôture ──
        if path == "/api/cloture/verifications":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(verifications_cloture(ex_id))
        if path == "/api/cloture/simuler":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(simuler_cloture(ex_id))

        # ── Immobilisations ──
        if path == "/api/immobilisations":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            actif_param = qs.get("actif", [None])[0]
            actif = None if actif_param is None else actif_param.lower() in ("1", "true", "yes")
            return self._json(lister_immobilisations(ex_id, actif=actif))
        if path == "/api/immobilisations/plan":
            immo_id = qs.get("id", [None])[0]
            if not immo_id:
                return self._json({"error": "id requis"}, 400)
            return self._json(plan_amortissement(int(immo_id)))
        if path == "/api/immobilisations/resume":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(resume_immobilisations(ex_id))

        # ── Emprunts ──
        if path == "/api/emprunts":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(lister_emprunts(ex_id))
        if path == "/api/emprunts/tableau":
            emp_id = qs.get("id", [None])[0]
            if not emp_id:
                return self._json({"error": "id requis"}, 400)
            return self._json(tableau_amortissement(int(emp_id)))
        if path == "/api/emprunts/resume":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(resume_emprunts(ex_id))

        # ── Catégories ──
        if path == "/api/categories/regles":
            return self._json(lister_regles())
        if path == "/api/categories/predefinies":
            return self._json(regles_predefinies())
        if path == "/api/categories/suggerer":
            ex_id = self._exercice_id(qs)
            if ex_id is None:
                return
            return self._json(suggerer_regles(ex_id))

        # Multi-societe
        if path == "/api/societes":
            import glob as _glob
            data_dir = os.environ.get("COMPTAPRO_DATA_DIR", os.path.dirname(DB_PATH))
            dbs = sorted(set(os.path.basename(d) for d in _glob.glob(os.path.join(data_dir, "*.db"))))
            return self._json({"current": os.path.basename(DB_PATH), "available": dbs})
        if path == "/api/societes/switch" and "db" in qs:
            new_db = qs["db"][0]
            if ".." in new_db or "/" in new_db or "\\" in new_db:
                return self._json({"error": "Nom de base invalide"}, 400)
            import comptable.db as _dbmod
            data_dir = os.environ.get("COMPTAPRO_DATA_DIR", os.path.dirname(_dbmod.DB_PATH))
            full_path = os.path.join(data_dir, new_db)
            if not os.path.exists(full_path):
                old = _dbmod.DB_PATH
                try:
                    _dbmod.DB_PATH = full_path
                    _dbmod.init_db()
                finally:
                    _dbmod.DB_PATH = old
            _dbmod.DB_PATH = full_path
            _dbmod.init_db()
            return self._json({"success": True, "db": new_db, "path": full_path})

        # Fichiers statiques
        if path == "/" or path == "":
            self.path = "/index.html"
        self._serve_static()

    @staticmethod
    def _detect_lan_ip():
        """Detect the machine's LAN IP (192.168.x.x / 10.x.x.x / 172.16-31.x.x)."""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return None

    def _serve_static(self):
        """Serve static files with proper Content-Type charset."""
        path = self.path
        ct_map = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".ico": "image/x-icon",
            ".woff2": "font/woff2",
        }
        ext = os.path.splitext(path)[1].lower()
        filepath = os.path.join(STATIC_DIR, path.lstrip("/"))
        if not os.path.isfile(filepath):
            self.send_error(404)
            return
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ct_map.get(ext, "application/octet-stream"))
            self.send_header("Content-Length", len(data))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self.send_error(404)

    # ── POST ────────────────────────────────────────────────────────
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Multipart (upload CSV)
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" in content_type and path == "/api/banque/import":
            return self._handle_csv_import(content_type)

        # ── Pieces jointes upload (multipart) ──
        if "multipart/form-data" in content_type and path == "/api/pj/upload":
            return self._handle_pj_upload(content_type)

        data = self._read_json()

        # Exercices
        if path == "/api/exercices":
            try:
                eid = creer_exercice(data["libelle"], data["date_debut"], data["date_fin"])
                return self._json({"id": eid, "ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # Écritures
        if path == "/api/ecritures":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id")
                if not ex_id:
                    return self._json({"error": "Aucun exercice actif"}, 400)
                eid = saisir_ecriture(
                    ex_id, data["journal"], data["date"], data["libelle"],
                    data["lignes"], data.get("piece"), data.get("reference"),
                )
                return self._json({"id": eid, "ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # Factures
        if path == "/api/factures":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id")
                if not ex_id:
                    return self._json({"error": "Aucun exercice actif"}, 400)
                # Adapte les champs du frontend (client, objet, lignes format simplifié)
                lignes_adaptees = []
                for l in data.get("lignes", []):
                    lignes_adaptees.append({
                        "description": l.get("description", ""),
                        "quantite": float(l.get("quantite", l.get("qte", 1)) or 1),
                        "prix_unitaire": float(l.get("prix_unitaire", l.get("pu", 0)) or 0),
                        "tva_taux": float(l.get("tva_taux", l.get("tva", 20)) or 0),
                    })
                fid = creer_facture(
                    ex_id, data["type"], data["date"], lignes_adaptees,
                    client_nom=data.get("client") or data.get("client_nom"),
                    echeance=data.get("echeance"),
                    notes=data.get("objet") or data.get("notes"),
                )
                return self._json({"id": fid, "ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # Générer écriture depuis facture
        if path.startswith("/api/factures/") and path.endswith("/ecriture"):
            parts = path.split("/")
            if len(parts) == 5 and parts[3].isdigit():
                fid = int(parts[3])
                try:
                    eid = generer_ecriture_facture(fid)
                    return self._json({"ecriture_id": eid, "ok": True})
                except Exception as e:
                    return self._json({"error": str(e)}, 400)

        # Banque - import CSV via JSON
        if path == "/api/banque/import":
            try:
                from comptable.banque import importer_csv_text
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                csv_text = data.get("csv", "")
                if not csv_text:
                    return self._json({"error": "Contenu CSV vide"}, 400)
                nb = importer_csv_text(ex_id, csv_text, data.get("compte_bancaire", "512"))
                return self._json({"ok": True, "nb_lignes": nb})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # Rapprochement automatique
        if path == "/api/banque/auto-match":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                return self._json(auto_match_rapprochement(ex_id))
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # Sauvegarde template facture
        if path == "/api/factures/templates":
            try:
                self._save_template(data)
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # Rapprocher une ligne
        if path.startswith("/api/banque/rapprocher"):
            try:
                ligne_id = data.get("ligne_id")
                ecriture_id = data.get("ecriture_id")
                rapprocher(ligne_id, ecriture_id)
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # Relances - créer scénario
        if path == "/api/relances/scenarios":
            try:
                sid = creer_scenario(
                    data["nom"],
                    data.get("conditions_json", "{}"),
                    data["modele_email"],
                    data["delai_jours"],
                )
                return self._json({"id": sid, "ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # Budget - définir
        if path == "/api/budget/definir":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                definir_budget(
                    ex_id, data["compte"], data["mois"],
                    data["montant"], data.get("notes"),
                )
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # Budget - import CSV
        if path == "/api/budget/importer":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                nb = importer_budget_csv(ex_id, data["chemin"])
                return self._json({"ok": True, "nb_lignes": nb})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # Notes de frais - créer
        if path == "/api/notes-frais":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                nid = creer_note(
                    ex_id, data["date"], data["description"],
                    data.get("categorie", "divers"),
                    data["montant_ht"],
                    data.get("tva_taux", 0),
                    data.get("employe", "Moi"),
                    data.get("justificatif"),
                )
                return self._json({"id": nid, "ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # Notes de frais - valider
        if path.startswith("/api/notes-frais/") and path.endswith("/valider"):
            parts = path.split("/")
            if len(parts) == 5 and parts[3].isdigit():
                try:
                    valider_note(int(parts[3]))
                    return self._json({"ok": True})
                except Exception as e:
                    return self._json({"error": str(e)}, 400)

        # Notes de frais - générer écriture
        if path.startswith("/api/notes-frais/") and path.endswith("/ecriture"):
            parts = path.split("/")
            if len(parts) == 5 and parts[3].isdigit():
                try:
                    eid = generer_ecriture_note(int(parts[3]))
                    return self._json({"ecriture_id": eid, "ok": True})
                except Exception as e:
                    return self._json({"error": str(e)}, 400)

        # ── Email : envoyer facture ──
        if path.startswith("/api/factures/") and path.endswith("/envoyer"):
            parts = path.split("/")
            if len(parts) == 5 and parts[3].isdigit():
                try:
                    dest = data.get("destinataire")
                    result = envoyer_facture_email(int(parts[3]), dest)
                    return self._json(result)
                except Exception as e:
                    return self._json({"error": str(e)}, 400)

        # ── Email : envoyer relance ──
        if path.startswith("/api/relances/envoyer/"):
            try:
                fid = data["facture_id"]
                sid = data.get("scenario_id")
                result = envoyer_relance_email(fid, sid, data.get("destinataire"))
                return self._json(result)
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Email : relances auto ──
        if path == "/api/relances/envoyer-auto":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                return self._json(envoyer_relances_auto(ex_id))
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Email : config SMTP ──
        if path == "/api/email/config":
            try:
                self._set_parametres(data)
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Lettrage : créer ──
        if path == "/api/lettrage":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                lid = creer_lettrage(ex_id)
                return self._json({"id": lid, "ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Lettrage : ajouter ligne ──
        if path.startswith("/api/lettrage/") and path.endswith("/ligne"):
            try:
                lid = int(path.split("/")[3])
                ajouter_ligne_lettrage(
                    lid, data["ecriture_id"], data["ligne_id"],
                    data["compte"], data["montant"], data["sens"])
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Prévisionnel ──
        if path == "/api/previsionnel":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                pid = ajouter_prevision(
                    ex_id, data["mois"], data["categorie"],
                    data["compte"], data["libelle"], data["montant"],
                    data.get("probabilite", 1.0),
                    data.get("recurrence", "ponctuel"),
                )
                return self._json({"id": pid, "ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Zone Achats ──
        if path == "/api/achats":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                aid = ajouter_achat(
                    ex_id, data["fournisseur"], data["date_facture"],
                    data["description"], data["montant_ttc"],
                    data.get("compte_charge", "607"),
                    data.get("tva_taux", 20.0),
                    data.get("numero_facture"),
                )
                return self._json({"id": aid, "ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)
        if path.startswith("/api/achats/") and path.endswith("/valider"):
            parts = path.split("/")
            if len(parts) == 4 and parts[2].isdigit():
                try:
                    valider_achat(int(parts[2]), data.get("valide_par", "comptable"))
                    return self._json({"ok": True})
                except Exception as e:
                    return self._json({"error": str(e)}, 400)
        if path.startswith("/api/achats/") and path.endswith("/rejeter"):
            parts = path.split("/")
            if len(parts) == 4 and parts[2].isdigit():
                try:
                    rejeter_achat(int(parts[2]), data.get("commentaire", ""))
                    return self._json({"ok": True})
                except Exception as e:
                    return self._json({"error": str(e)}, 400)
        if path.startswith("/api/achats/") and path.endswith("/ecriture"):
            parts = path.split("/")
            if len(parts) == 4 and parts[2].isdigit():
                try:
                    eid = generer_ecriture_achat(int(parts[2]))
                    return self._json({"ecriture_id": eid, "ok": True})
                except Exception as e:
                    return self._json({"error": str(e)}, 400)

        # ── Abonnements - créer ──
        if path == "/api/abonnements":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                aid = creer_abonnement(
                    ex_id, data["client_nom"], data["description"],
                    data["montant_ht"], data["periodicite"],
                    data.get("tva_taux", 20.0),
                    data.get("jour_facturation", 1),
                    data.get("date_debut"),
                    data.get("date_fin"),
                    data.get("compte_produit", "706"),
                )
                return self._json({"id": aid, "ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Paie - import CSV ──
        if path == "/api/paie/importer":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                chemin = data["chemin"]
                result = importer_paie_csv(ex_id, chemin)
                return self._json(result)
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Bons - créer ──
        if path == "/api/bons":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                bid = creer_bon(
                    ex_id, data["type"], data["sous_type"],
                    data["date"], data.get("client_nom", ""),
                    data["lignes"],
                    echeance=data.get("echeance"),
                    notes=data.get("notes"),
                )
                return self._json({"id": bid, "ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Bons - convertir en facture ──
        if path.startswith("/api/bons/") and path.endswith("/convertir"):
            try:
                bon_id = int(path.split("/")[3])
                fid = convertir_bon_en_facture(bon_id)
                return self._json({"facture_id": fid, "ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Clôture - exécuter ──
        if path == "/api/cloture/executer":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                rapport = cloturer_exercice(ex_id)
                return self._json(rapport)
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Clôture - réouvrir ──
        if path == "/api/cloture/reouvrir":
            try:
                ex_id = data.get("exercice_id")
                reouvrir_exercice(ex_id)
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Immobilisations ──
        if path == "/api/immobilisations":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                iid = ajouter_immobilisation(
                    ex_id, data["compte_immo"], data["compte_amort"],
                    data["designation"], data["date_acquisition"],
                    data["valeur_acquisition"], data["duree_annees"],
                    data.get("mode", "lineaire"),
                    data.get("coefficient_degressif", 1.75),
                    data.get("valeur_residuelle", 0),
                )
                return self._json({"id": iid, "ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)
        if path == "/api/immobilisations/amortir":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                result = calculer_amortissements(ex_id, data.get("immo_id"))
                return self._json(result)
            except Exception as e:
                return self._json({"error": str(e)}, 400)
        if path == "/api/immobilisations/ceder":
            try:
                result = ceder_immobilisation(
                    data["id"], data["date_cession"], data["prix_cession"]
                )
                return self._json(result)
            except Exception as e:
                return self._json({"error": str(e)}, 400)
        if path == "/api/immobilisations/ecritures":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                result = generer_ecritures_amortissement(ex_id, data["immo_id"])
                return self._json(result)
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Emprunts ──
        if path == "/api/emprunts":
            try:
                ex_id = data.get("exercice_id") or (exercice_actif() or {}).get("id") or 1
                eid = ajouter_emprunt(
                    ex_id, data["designation"], data["date_debut"],
                    data["montant"], data["taux_annuel"], data["duree_mois"],
                    data.get("periodicite", "mensuelle"),
                    data.get("type_amortissement", "constant"),
                    data.get("frais_dossier", 0),
                    data.get("assurance", 0),
                )
                return self._json({"id": eid, "ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)
        if path == "/api/emprunts/generer":
            try:
                eid = data["id"]
                result = generer_tableau_amortissement(eid)
                return self._json(result)
            except Exception as e:
                return self._json({"error": str(e)}, 400)
        if path == "/api/emprunts/ecriture":
            try:
                result = generer_ecriture_echeance(data["emprunt_id"], data["numero"])
                return self._json(result)
            except Exception as e:
                return self._json({"error": str(e)}, 400)
        if path == "/api/emprunts/cloturer":
            try:
                result = cloturer_emprunt(data["id"])
                return self._json(result)
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Catégories ──
        if path == "/api/categories/regles":
            try:
                rid = ajouter_regle(
                    data["compte_cible"], data["mot_cle"],
                    data.get("champ", "libelle"), data.get("priorite", 0),
                )
                return self._json({"id": rid, "ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)
        if path == "/api/categories/categoriser":
            try:
                rid = data.get("releve_id")
                if not rid:
                    return self._json({"error": "releve_id requis"}, 400)
                result = categoriser_releve(rid)
                return self._json(result)
            except Exception as e:
                return self._json({"error": str(e)}, 400)
        if path == "/api/categories/ligne":
            try:
                result = categoriser_ligne(
                    data.get("libelle", ""), data.get("montant", 0)
                )
                return self._json(result or {})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Pieces jointes POST ──
        if path == "/api/pj/lier":
            try:
                lier_pj(
                    int(data["id"]),
                    ecriture_id=data.get("ecriture_id"),
                    facture_id=data.get("facture_id"),
                    note_id=data.get("note_id"),
                    categorie=data.get("categorie"),
                    tags=data.get("tags"),
                )
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)
        if path == "/api/pj/supprimer":
            try:
                supprimer_pj(int(data["id"]))
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        return self._json({"error": "Route inconnue"}, 404)

    # ── PUT ─────────────────────────────────────────────────────────
    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path

        data = self._read_json()

        # Changer statut facture
        if path.startswith("/api/factures/") and path.endswith("/statut"):
            parts = path.split("/")
            if len(parts) == 5 and parts[3].isdigit():
                fid = int(parts[3])
                try:
                    changer_statut(fid, data["statut"])
                    return self._json({"ok": True})
                except Exception as e:
                    return self._json({"error": str(e)}, 400)

        # Paramètres
        if path == "/api/parametres":
            try:
                self._set_parametres(data)
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # Suggérer compte pour une ligne de relevé
        if path.startswith("/api/banque/suggerer/"):
            parts = path.split("/")
            if len(parts) == 4 and parts[3].isdigit():
                lid = int(parts[3])
                try:
                    compte = suggerer_compte(lid)
                    return self._json({"compte_suggere": compte, "ok": True})
                except Exception as e:
                    return self._json({"error": str(e)}, 400)

        # Relances - supprimer scénario
        if path.startswith("/api/relances/scenarios/") and path.count("/") == 4:
            try:
                sid = int(path.split("/")[3])
                return self._json(supprimer_scenario(sid))
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Bons - convertir bon commande -> bon livraison ──
        if path.startswith("/api/bons/") and path.endswith("/livraison"):
            try:
                bon_id = int(path.split("/")[3])
                convertir_bon_en_livraison(bon_id)
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        return self._json({"error": "Route inconnue"}, 404)

    # ── DELETE ────────────────────────────────────────────────────────
    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # ── Lettrage ──
        if path.startswith("/api/lettrage/") and path.count("/") == 3:
            try:
                lid = int(path.split("/")[2])
                return self._json(supprimer_lettrage(lid))
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Désactiver abonnement ──
        if path.startswith("/api/abonnements/") and path.endswith("/desactiver"):
            try:
                aid = int(path.split("/")[3])
                desactiver_abonnement(aid)
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        # ── Supprimer règle catégorisation ──
        if path.startswith("/api/categories/regles/") and path.count("/") == 4:
            try:
                rid = int(path.split("/")[3])
                return self._json(supprimer_regle(rid))
            except Exception as e:
                return self._json({"error": str(e)}, 400)

        return self._json({"error": "Route inconnue"}, 404)

    def _list_ecritures(self, exercice_id: int, q: str = "", limit: int = 200, offset: int = 0) -> list[dict]:
        """Liste les écritures avec résumé comptes/débit/crédit et pagination."""
        conn = get_db()
        query = "SELECT * FROM ecritures WHERE exercice_id = ?"
        params = [exercice_id]
        if q:
            ql = f"%{q}%"
            query += """ AND (id IN (
                SELECT DISTINCT ecriture_id FROM lignes_ecriture WHERE compte LIKE ?
            ) OR libelle LIKE ? OR piece LIKE ? OR reference LIKE ?)"""
            params.extend([ql, ql, ql, ql])
        query += " ORDER BY date DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            totals = conn.execute(
                "SELECT SUM(debit) as td, SUM(credit) as tc, GROUP_CONCAT(DISTINCT compte) as comptes FROM lignes_ecriture WHERE ecriture_id = ?",
                (r["id"],),
            ).fetchone()
            d = dict(r)
            d["total_debit"] = round(totals["td"] or 0, 2)
            d["total_credit"] = round(totals["tc"] or 0, 2)
            d["comptes"] = totals["comptes"] or ""
            result.append(d)
        conn.close()
        return result

    # ── Helpers ─────────────────────────────────────────────────────
    def _read_json(self):
        """Lit et parse le body JSON, gère les problèmes d'encodage."""
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len else b"{}"
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return json.loads(body.decode("latin-1"))

    def _exercice_id(self, qs):
        raw = qs.get("exercice_id", [None])[0]
        if raw:
            return int(raw)
        actif = exercice_actif()
        if actif:
            return actif["id"]
        self._json({"error": "Aucun exercice actif. Créez-en un."}, 400)
        return None

    def _compte_dict(self, c):
        return {"numero": c.numero, "libelle": c.libelle, "classe": c.classe, "sens": c.sens}

    def _get_parametres(self):
        conn = get_db()
        rows = conn.execute("SELECT cle, valeur FROM parametres").fetchall()
        conn.close()
        return {r["cle"]: r["valeur"] for r in rows}

    def _set_parametres(self, data: dict):
        conn = get_db()
        for cle, valeur in data.items():
            conn.execute(
                "INSERT INTO parametres (cle, valeur) VALUES (?,?) "
                "ON CONFLICT(cle) DO UPDATE SET valeur=excluded.valeur",
                (cle, str(valeur)),
            )
        conn.commit()
        conn.close()

    def _handle_csv_import(self, content_type):
        """Parse un upload multipart/form-data et importe le CSV (sans cgi, retiré en 3.13)."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len)

            # Extraire le boundary
            boundary = None
            for part in content_type.split(";"):
                part = part.strip()
                if part.startswith("boundary="):
                    boundary = part.split("=", 1)[1].strip('"')
            if not boundary:
                return self._json({"error": "Boundary multipart introuvable"}, 400)

            # Split par boundary
            boundary_bytes = ("--" + boundary).encode("utf-8")
            parts = body.split(boundary_bytes)[1:-1]  # premier = préambule, dernier = --boundary--

            csv_content = None
            exercice_id_val = None
            for part in parts:
                part = part.lstrip(b"\r\n").rstrip(b"\r\n--")
                # Séparer headers du contenu
                header_end = part.find(b"\r\n\r\n")
                if header_end == -1:
                    continue
                headers_raw = part[:header_end].decode("utf-8", errors="replace")
                content = part[header_end + 4:]
                # Retirer le \r\n final
                if content.endswith(b"\r\n"):
                    content = content[:-2]

                # Détecter si c'est un fichier
                is_file = "filename=" in headers_raw
                name_match = re.search(r'name="([^"]+)"', headers_raw)
                name = name_match.group(1) if name_match else None

                if is_file:
                    csv_content = content.decode("utf-8-sig")
                elif name == "exercice_id":
                    exercice_id_val = int(content.decode("utf-8").strip())
                elif name == "compte_bancaire":
                    pass  # optionnel

            if csv_content is None:
                return self._json({"error": "Aucun fichier CSV dans le formulaire"}, 400)

            ex_id = exercice_id_val or (exercice_actif() or {}).get("id") or 1

            # Écrire le CSV dans un fichier temporaire
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
            tmp.write(csv_content)
            tmp.close()

            nb = importer_csv(ex_id, "512", tmp.name)
            os.unlink(tmp.name)
            return self._json({"ok": True, "nb_lignes": nb})
        except Exception as e:
            return self._json({"error": str(e)}, 400)

    def _handle_pj_upload(self, content_type):
        """Handle multipart file upload for pieces jointes (email.parser)."""
        try:
            import email.parser
            cl = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(cl)
            raw = ("Content-Type: " + content_type + "\r\n\r\n").encode() + body
            msg = email.parser.BytesParser().parsebytes(raw)
            categorie = "ticket"
            date_prise = None
            tags = ""
            files = []
            for part in msg.walk():
                cd = part.get("Content-Disposition", "")
                pd = part.get_payload(decode=True)
                if pd is None:
                    continue
                m = re.search(r'name="(?P<n>[^"]+)"', cd)
                name = m.group("n") if m else ""
                if name == "categorie":
                    categorie = pd.decode()
                elif name == "date_prise":
                    date_prise = pd.decode()
                elif name == "tags":
                    tags = pd.decode()
                elif "filename=" in cd:
                    fn = re.search(r'filename="(?P<f>[^"]+)"', cd)
                    filename = fn.group("f") if fn else "upload.jpg"
                    mime_type = part.get_content_type() or "image/jpeg"
                    pj = ajouter_pj(filename, pd, type_mime=mime_type,
                                    categorie=categorie, date_prise=date_prise, tags=tags)
                    files.append(pj)
            return self._json({"success": True, "uploaded": len(files), "files": files})
        except Exception as e:
            return self._json({"error": str(e)}, 400)

    def _read_body(self) -> str:
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len else b"{}"
        return body.decode("utf-8")

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html_str: str, status=200):
        body = html_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    # ── Nouvelles méthodes helpers ──────────────────────────────────
    def _search_all(self, exercice_id: int, q: str) -> dict:
        """Recherche globale dans les écritures, factures, comptes."""
        if not q:
            return {"results": []}
        ql = f"%{q}%"
        conn = get_db()
        results = []
        # Écritures
        for r in conn.execute("SELECT id,date,journal,libelle FROM ecritures WHERE exercice_id=? AND (libelle LIKE ? OR piece LIKE ?) LIMIT 10", [exercice_id, ql, ql]):
            results.append({"type": "ecriture", "id": r["id"], "label": f"{r['date']} {r['journal']} {r['libelle']}"})
        # Factures
        for r in conn.execute("SELECT id,numero,client_nom,total_ttc FROM factures WHERE exercice_id=? AND (numero LIKE ? OR client_nom LIKE ?) LIMIT 10", [exercice_id, ql, ql]):
            results.append({"type": "facture", "id": r["id"], "label": f"{r['numero']} {r['client_nom']} {r['total_ttc']}€"})
        # Comptes
        for r in conn.execute("SELECT DISTINCT compte FROM lignes_ecriture l JOIN ecritures e ON e.id=l.ecriture_id WHERE e.exercice_id=? AND l.compte LIKE ? LIMIT 10", [exercice_id, ql]):
            results.append({"type": "compte", "id": r["compte"], "label": r["compte"]})
        conn.close()
        return {"results": results}

    def _get_notifications(self, exercice_id: int) -> dict:
        """Notifications : factures en retard, TVA à payer, rapprochements en attente."""
        conn = get_db()
        nb_retard = conn.execute("SELECT COUNT(*) AS n FROM factures WHERE exercice_id=? AND statut='en_retard'", [exercice_id]).fetchone()["n"]
        nb_non_rapp = conn.execute("""SELECT COUNT(*) AS n FROM lignes_releve lr JOIN releves_bancaires rb ON rb.id=lr.releve_id WHERE rb.exercice_id=? AND lr.rapproche=0""", [exercice_id]).fetchone()["n"]
        conn.close()
        # TVA à payer = collectée - déductible
        tva = tva_preview(exercice_id)
        notifs = []
        if nb_retard > 0:
            notifs.append({"type": "warning", "msg": f"{nb_retard} facture(s) en retard", "action": "factures"})
        if tva.get("a_payer", 0) > 0:
            notifs.append({"type": "info", "msg": f"TVA à payer : {tva['a_payer']:.2f} €", "action": "tva"})
        if nb_non_rapp > 0:
            notifs.append({"type": "info", "msg": f"{nb_non_rapp} ligne(s) bancaire(s) non rapprochée(s)", "action": "banque"})
        return {"notifications": notifs, "count": len(notifs)}

    def _export_csv(self, exercice_id: int, typ: str):
        """Export CSV des écritures."""
        if typ == "ecritures":
            ecritures = self._list_ecritures(exercice_id, "", 10000, 0)
            import csv, io
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["Date", "Journal", "Pièce", "Libellé", "Comptes", "Débit", "Crédit"])
            for e in ecritures:
                w.writerow([e.get("date",""), e.get("journal",""), e.get("piece",""), e.get("libelle",""), e.get("comptes",""), e.get("total_debit",0), e.get("total_credit",0)])
            body = buf.getvalue().encode("utf-8-sig")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=ecritures.csv")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

    def _get_templates(self) -> list[dict]:
        conn = get_db()
        rows = conn.execute("SELECT cle, valeur FROM parametres WHERE cle LIKE 'template_%'").fetchall()
        conn.close()
        return [{"name": r["cle"].replace("template_",""), "data": r["valeur"]} for r in rows]

    def _save_template(self, data: dict):
        name = data.get("name", "sans_nom")
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO parametres (cle, valeur) VALUES (?,?)", (f"template_{name}", json.dumps(data.get("lignes", []), ensure_ascii=False)))
        conn.commit()
        conn.close()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        print(f"[compta] {args[0]}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Serveur compta style Pennylane")
    parser.add_argument("--port", type=int, default=8080, help="Port (défaut: 8080)")
    args = parser.parse_args()

    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), ComptaHandler)
    print(f"Agent comptable -> http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
        server.server_close()


if __name__ == "__main__":
    main()
