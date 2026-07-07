"""
Envoi d'emails SMTP pour factures et relances.
Stdlib uniquement : smtplib + email.mime.
"""

import json
import smtplib
import ssl
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from .db import get_db
from .audit import log_action


def config_smtp() -> dict:
    """Lit les paramètres SMTP depuis la table parametres."""
    conn = get_db()
    rows = conn.execute(
        "SELECT cle, valeur FROM parametres WHERE cle LIKE 'smtp_%' OR cle = 'email_signature'"
    ).fetchall()
    conn.close()

    cfg = {}
    for r in rows:
        cfg[r["cle"]] = r["valeur"]

    return {
        "host": cfg.get("smtp_host", ""),
        "port": int(cfg.get("smtp_port", "587")),
        "user": cfg.get("smtp_user", ""),
        "password": cfg.get("smtp_password", ""),
        "from": cfg.get("smtp_from", ""),
        "use_tls": cfg.get("smtp_use_tls", "1") == "1",
        "signature": cfg.get("email_signature", ""),
    }


def tester_connexion(config: dict) -> tuple:
    """Teste la connexion SMTP. Retourne (ok: bool, message: str)."""
    if not config.get("host") or not config.get("user"):
        return (False, "Configuration SMTP incomplète (host, user requis).")

    try:
        ctx = ssl.create_default_context() if config.get("use_tls") else None
        if config.get("use_tls"):
            server = smtplib.SMTP(config["host"], config["port"], timeout=10)
            server.starttls(context=ctx)
        else:
            server = smtplib.SMTP(config["host"], config["port"], timeout=10)

        server.login(config["user"], config["password"])
        server.quit()
        return (True, "Connexion SMTP réussie.")
    except smtplib.SMTPAuthenticationError:
        return (False, "Erreur d'authentification SMTP. Vérifiez user/password.")
    except smtplib.SMTPConnectError as e:
        return (False, f"Impossible de se connecter au serveur SMTP : {e}")
    except smtplib.SMTPException as e:
        return (False, f"Erreur SMTP : {e}")
    except OSError as e:
        return (False, f"Erreur réseau : {e}")


def _envoyer_email_smtp(
    destinataire: str,
    sujet: str,
    corps_html: str,
    piece_jointe: Optional[bytes] = None,
    nom_piece: str = "document.pdf",
) -> dict:
    """Envoie un email via SMTP. Retourne {'ok': True/False, 'message': str}."""
    cfg = config_smtp()
    if not cfg["host"] or not cfg["from"]:
        return {"ok": False, "message": "Configuration SMTP incomplète."}

    try:
        msg = MIMEMultipart("mixed")
        msg["From"] = cfg["from"]
        msg["To"] = destinataire
        msg["Subject"] = sujet

        # Attacher le HTML
        html_part = MIMEText(corps_html, "html", "utf-8")
        msg.attach(html_part)

        # Pièce jointe
        if piece_jointe:
            pdf_part = MIMEApplication(piece_jointe, _subtype="pdf")
            pdf_part.add_header("Content-Disposition", "attachment", filename=nom_piece)
            msg.attach(pdf_part)

        ctx = ssl.create_default_context() if cfg["use_tls"] else None
        if cfg["use_tls"]:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
            server.starttls(context=ctx)
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)

        server.login(cfg["user"], cfg["password"])
        server.sendmail(cfg["from"], destinataire, msg.as_string())
        server.quit()

        return {"ok": True, "message": f"Email envoyé à {destinataire}"}
    except smtplib.SMTPAuthenticationError:
        return {"ok": False, "message": "Erreur d'authentification SMTP."}
    except smtplib.SMTPException as e:
        return {"ok": False, "message": f"Erreur SMTP : {e}"}
    except OSError as e:
        return {"ok": False, "message": f"Erreur réseau : {e}"}


def _generer_corps_facture(fact: dict, params_entreprise: dict) -> str:
    """Génère le corps HTML d'un email de facture."""
    sig = params_entreprise.get("email_signature", "")
    entreprise = params_entreprise.get("nom_entreprise", "Entreprise")
    return f"""<!DOCTYPE html><html><body style="font-family:sans-serif">
<p>Bonjour {fact.get('client_nom', '') or 'Client'},</p>
<p>Veuillez trouver ci-joint votre facture <strong>{fact.get('numero', '')}</strong>
d'un montant de <strong>{fact.get('total_ttc', 0):,.2f} €</strong>
{('à régler avant le ' + fact['echeance']) if fact.get('echeance') else ''}.</p>
<p>Cordialement,<br>{entreprise}</p>
{sig and '<hr><p style="color:#666;font-size:0.9em">' + sig.replace(chr(10), '<br>') + '</p>' or ''}
</body></html>"""


def envoyer_email(
    destinataire: str,
    sujet: str,
    corps_html: str,
    piece_jointe: Optional[bytes] = None,
) -> dict:
    """Envoie un email générique via SMTP."""
    return _envoyer_email_smtp(destinataire, sujet, corps_html, piece_jointe)


def envoyer_facture_email(
    facture_id: int,
    destinataire: Optional[str] = None,
) -> dict:
    """Envoie une facture par email.
    Récupère la facture, génère le template HTML, envoie.
    Log l'action dans piste_audit.
    Change le statut facture en 'envoyee' si brouillon.
    """
    conn = get_db()

    f = conn.execute("SELECT * FROM factures WHERE id = ?", (facture_id,)).fetchone()
    if not f:
        conn.close()
        return {"ok": False, "message": f"Facture {facture_id} introuvable"}
    fact = dict(f)

    dest = destinataire or fact.get("client_email", "")
    if not dest:
        conn.close()
        return {"ok": False, "message": "Aucun destinataire (email client vide)."}

    params_rows = conn.execute(
        "SELECT cle, valeur FROM parametres"
    ).fetchall()
    params = {r["cle"]: r["valeur"] for r in params_rows}
    conn.close()

    corps = _generer_corps_fact(fact, params)

    from .pdf_templates import template_facture
    html_pdf = template_facture(fact, [], params)
    # Pas de vrai PDF, on envoie le HTML en pièce jointe HTML
    piece = html_pdf.encode("utf-8")

    result = _envoyer_email_smtp(
        dest,
        f"Facture {fact['numero']}",
        corps,
        piece_jointe=piece,
        nom_piece=f"{fact['numero']}.html",
    )

    if result["ok"]:
        log_action("facture", facture_id, "envoi_email",
                   {"destinataire": dest, "facture": fact["numero"]})

        # Change statut brouillon → envoyee
        conn2 = get_db()
        if fact["statut"] == "brouillon":
            conn2.execute("UPDATE factures SET statut='envoyee' WHERE id=?", (facture_id,))
            conn2.commit()
        conn2.close()

    return result


def envoyer_relance_email(
    facture_id: int,
    scenario_id: Optional[int] = None,
    destinataire: Optional[str] = None,
) -> dict:
    """Envoie un email de relance pour une facture.
    Utilise le modèle du scénario et remplace les variables.
    Log dans piste_audit et historique_relances.
    """
    conn = get_db()

    f = conn.execute("SELECT * FROM factures WHERE id = ?", (facture_id,)).fetchone()
    if not f:
        conn.close()
        return {"ok": False, "message": f"Facture {facture_id} introuvable"}
    fact = dict(f)

    dest = destinataire or fact.get("client_email", "")
    if not dest:
        conn.close()
        return {"ok": False, "message": "Aucun destinataire."}

    # Récupérer le modèle email
    modele = ""
    scenario_nom = "Manuelle"
    if scenario_id:
        sc = conn.execute(
            "SELECT * FROM scenarios_relance WHERE id = ?", (scenario_id,)
        ).fetchone()
        if sc:
            modele = sc["modele_email"]
            scenario_nom = sc["nom"]

    if not modele:
        modele = """<p>Bonjour {{client}},</p>
<p>Votre facture {{facture_num}} de {{montant}} € arrive à échéance le {{date_echeance}}.
Merci de bien vouloir procéder au règlement.</p>
<p>Cordialement.</p>"""

    # Remplacer les variables
    echeance = fact.get("echeance") or fact.get("date") or ""
    corps = modele.replace("{{client}}", fact.get("client_nom", "Client"))
    corps = corps.replace("{{montant}}", f"{fact.get('total_ttc', 0):,.2f}")
    corps = corps.replace("{{facture_num}}", fact.get("numero", ""))
    corps = corps.replace("{{date_echeance}}", echeance)

    sujet = f"Relance — Facture {fact['numero']}"

    result = _envoyer_email_smtp(dest, sujet, corps)

    # Enregistrer dans historique_relances
    msg = f"Relance envoyée à {dest}" if result["ok"] else f"Échec relance : {result['message']}"
    statut_hist = "envoye" if result["ok"] else "echec"
    conn.execute(
        """INSERT INTO historique_relances (facture_id, scenario_id, statut, message)
           VALUES (?, ?, ?, ?)""",
        (facture_id, scenario_id, statut_hist, msg),
    )
    conn.commit()
    conn.close()

    if result["ok"]:
        log_action("facture", facture_id, "envoi_email",
                   {"type": "relance", "destinataire": dest, "scenario": scenario_nom})

    return result


def envoyer_relances_auto(exercice_id: int) -> dict:
    """Exécute les relances automatiques avec envoi réel d'emails.
    Similaire à executer_relances mais envoie vraiment les emails.
    """
    from datetime import date, datetime as dt

    conn = get_db()
    today = date.today()

    factures = conn.execute(
        """SELECT id, client_nom, client_email, total_ttc, date, echeance, statut
           FROM factures
           WHERE exercice_id = ?
             AND type = 'facture'
             AND statut NOT IN ('payee', 'annulee')
           ORDER BY echeance, id""",
        (exercice_id,),
    ).fetchall()

    scenarios = conn.execute(
        "SELECT * FROM scenarios_relance WHERE actif = 1 ORDER BY delai_jours"
    ).fetchall()
    conn.close()

    nb_envoyes = 0
    nb_echecs = 0
    details = []

    for fact in factures:
        fact_date = fact["echeance"] or fact["date"]
        try:
            d = dt.strptime(fact_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        retard_jours = (today - d).days
        if retard_jours <= 0:
            continue

        for scenario in scenarios:
            if retard_jours < scenario["delai_jours"]:
                continue

            # Vérifier si déjà envoyé
            conn2 = get_db()
            already = conn2.execute(
                "SELECT id FROM historique_relances WHERE facture_id=? AND scenario_id=? AND statut='envoye'",
                (fact["id"], scenario["id"]),
            ).fetchone()
            conn2.close()
            if already:
                continue

            result = envoyer_relance_email(fact["id"], scenario["id"],
                                           fact.get("client_email"))
            if result.get("ok"):
                nb_envoyes += 1
            else:
                nb_echecs += 1

            details.append({
                "facture_id": fact["id"],
                "scenario": scenario["nom"],
                "client": fact["client_nom"] or "?",
                "ok": result.get("ok", False),
                "message": result.get("message", ""),
            })

    return {"nb_envoyes": nb_envoyes, "nb_echecs": nb_echecs, "details": details}
