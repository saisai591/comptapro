"""
Templates HTML imprimables pour factures, balance, bilan, grand-livre.
Zéro dépendance externe : le navigateur fait le rendu PDF via Ctrl+P.
"""

from datetime import date


CSS_PRINT = """
<style>
  @page { size: A4; margin: 15mm 12mm 15mm 12mm; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font: 11px/1.4 'Helvetica Neue', Arial, sans-serif; color: #1a1a1a; }
  .header { display: flex; justify-content: space-between; margin-bottom: 20px; border-bottom: 2px solid #1a1a2e; padding-bottom: 10px; }
  .header h1 { font-size: 18px; color: #1a1a2e; }
  .header .right { text-align: right; font-size: 10px; color: #555; }
  .info { display: flex; gap: 40px; margin-bottom: 20px; }
  .info .col { flex: 1; }
  .info h3 { font-size: 10px; text-transform: uppercase; color: #888; margin-bottom: 4px; }
  .info p { font-size: 11px; margin-bottom: 2px; }
  table { width: 100%; border-collapse: collapse; margin: 16px 0; }
  th { background: #f5f5f5; text-align: left; padding: 6px 8px; font-size: 10px; text-transform: uppercase; color: #555; border-bottom: 1px solid #ddd; }
  td { padding: 6px 8px; border-bottom: 1px solid #eee; font-size: 11px; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .totals { margin-left: auto; width: 280px; margin-top: 16px; }
  .totals table td { border: none; padding: 4px 8px; }
  .totals .total-line td { border-top: 2px solid #1a1a2e; font-weight: bold; font-size: 13px; }
  .footer { margin-top: 40px; font-size: 9px; color: #999; border-top: 1px solid #eee; padding-top: 10px; }
  .footer p { margin-bottom: 4px; }
  .mention { margin-top: 30px; font-size: 9px; color: #777; }
  .status { display: inline-block; padding: 2px 10px; border-radius: 10px; font-size: 10px; font-weight: bold; }
  .status-payee { background: #e8f5e9; color: #0a8f32; }
  .status-envoyee { background: #e3f2fd; color: #1565c0; }
  .status-brouillon { background: #fff3e0; color: #e65100; }
  .status-retard { background: #fdecea; color: #c0392b; }
  .title-row { margin-bottom: 20px; }
  .title-row h2 { font-size: 14px; color: #1a1a2e; }
</style>
"""


def _param_entreprise(conn):
    """Lit les paramètres entreprise."""
    rows = conn.execute("SELECT cle, valeur FROM parametres WHERE cle IN ('nom_entreprise','adresse','siret','email','iban','tel')").fetchall()
    return {r["cle"]: r["valeur"] for r in rows}


def _format_montant(v):
    if v is None:
        return "0,00"
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def template_facture(fact: dict, lignes: list[dict], params: dict) -> str:
    """Template HTML imprimable pour une facture."""
    entreprise = params.get("nom_entreprise", "Mon Entreprise")
    adresse = params.get("adresse", "")
    siret = params.get("siret", "")
    email = params.get("email", "")
    iban = params.get("iban", "")
    tel = params.get("tel", "")

    status_class = {
        "brouillon": "status-brouillon",
        "envoyee": "status-envoyee",
        "payee": "status-payee",
        "en_retard": "status-retard",
    }.get(fact.get("statut", ""), "")

    type_label = {"facture": "FACTURE", "devis": "DEVIS", "avoir": "AVOIR"}.get(fact.get("type", ""), "FACTURE")

    lignes_html = ""
    for l in lignes:
        total_ligne = (l["quantite"] or 0) * (l["prix_unitaire"] or 0)
        lignes_html += f"""<tr>
          <td>{l['description']}</td>
          <td class="num">{l['quantite']:.0f}</td>
          <td class="num">{_format_montant(l['prix_unitaire'])} €</td>
          <td class="num">{l['tva_taux']:.1f}%</td>
          <td class="num">{_format_montant(total_ligne)} €</td>
        </tr>"""

    total_ht = fact.get("total_ht", 0) or 0
    total_tva = fact.get("total_tva", 0) or 0
    total_ttc = fact.get("total_ttc", 0) or 0

    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>{type_label} {fact['numero']}</title>{CSS_PRINT}</head><body>
<div class="header">
  <div><h1>{entreprise}</h1><p>{adresse}</p><p>SIRET: {siret}</p></div>
  <div class="right">
    <h1>{type_label}</h1>
    <p>N° {fact['numero']}</p>
    <p>Date: {fact['date']}</p>
    {f'<p>Échéance: {fact["echeance"]}</p>' if fact.get("echeance") else ''}
    <p><span class="status {status_class}">{fact.get('statut','').upper()}</span></p>
  </div>
</div>

<div class="info">
  <div class="col">
    <h3>Client</h3>
    <p><strong>{fact.get('client_nom') or fact.get('client') or '—'}</strong></p>
    {f'<p>{fact.get("client_adresse","")}</p>' if fact.get("client_adresse") else ''}
    {f'<p>{fact.get("client_email","")}</p>' if fact.get("client_email") else ''}
    {f'<p>SIRET: {fact.get("client_siret","")}</p>' if fact.get("client_siret") else ''}
  </div>
  <div class="col">
    <h3>Émetteur</h3>
    <p>{entreprise}</p>
    <p>{adresse}</p>
    {f'<p>{email}</p>' if email else ''}
    {f'<p>{tel}</p>' if tel else ''}
  </div>
</div>

{('<p style="margin-bottom:12px;font-style:italic;color:#555">' + (fact.get('notes') or fact.get('objet') or '') + '</p>') if (fact.get('notes') or fact.get('objet')) else ''}

<table>
  <thead><tr><th>Description</th><th class="num">Qté</th><th class="num">Prix unitaire</th><th class="num">TVA</th><th class="num">Total HT</th></tr></thead>
  <tbody>{lignes_html}</tbody>
</table>

<div class="totals">
  <table>
    <tr><td>Total HT</td><td class="num">{_format_montant(total_ht)} €</td></tr>
    <tr><td>Total TVA</td><td class="num">{_format_montant(total_tva)} €</td></tr>
    <tr class="total-line"><td>Total TTC</td><td class="num">{_format_montant(total_ttc)} €</td></tr>
  </table>
</div>

<div class="mention">
  {f'<p><strong>IBAN:</strong> {iban}</p>' if iban else ''}
  <p>TVA sur les débits — Escompte pour paiement anticipé: aucun</p>
  <p>En cas de retard de paiement, une indemnité forfaitaire de 40 € pour frais de recouvrement sera due (art. L.441-6 C. com.).</p>
</div>

<div class="footer">
  <p>{entreprise} — {adresse} — SIRET: {siret}</p>
</div>
</body></html>"""


def template_balance(balance: list[dict], exercice_libelle: str, params: dict) -> str:
    """Template HTML imprimable pour la balance."""
    entreprise = params.get("nom_entreprise", "Mon Entreprise")
    td = tc = sd = sc = 0.0
    rows = ""
    for l in balance:
        td += l["total_debit"]; tc += l["total_credit"]
        sd += l["solde_debit"]; sc += l["solde_credit"]
        rows += f"""<tr>
          <td>{l['compte']}</td>
          <td class="num">{_format_montant(l['total_debit'])}</td>
          <td class="num">{_format_montant(l['total_credit'])}</td>
          <td class="num">{_format_montant(l['solde_debit'])}</td>
          <td class="num">{_format_montant(l['solde_credit'])}</td>
        </tr>"""

    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>Balance - {exercice_libelle}</title>{CSS_PRINT}</head><body>
<div class="header"><div><h1>{entreprise}</h1><p class="title-row"><h2>Balance Générale — {exercice_libelle}</h2><p>Édité le {date.today().strftime('%d/%m/%Y')}</p></div></div>
<table><thead><tr><th>Compte</th><th class="num">Débit</th><th class="num">Crédit</th><th class="num">Solde Débit</th><th class="num">Solde Crédit</th></tr></thead><tbody>
{rows}
<tr style="font-weight:bold;border-top:2px solid #1a1a2e"><td>TOTAL</td><td class="num">{_format_montant(td)}</td><td class="num">{_format_montant(tc)}</td><td class="num">{_format_montant(sd)}</td><td class="num">{_format_montant(sc)}</td></tr>
</tbody></table>
<div class="footer"><p>{entreprise} — SIRET: {params.get('siret','')}</p></div>
</body></html>"""


def template_bilan(bilan: dict, exercice_libelle: str, params: dict) -> str:
    """Template HTML imprimable pour le bilan."""
    entreprise = params.get("nom_entreprise", "Mon Entreprise")

    actif_rows = ""
    for l in bilan.get("actif", []):
        actif_rows += f"<tr><td>{l.get('compte','')}</td><td>{l.get('libelle','')}</td><td class=\"num\">{_format_montant(l.get('solde_debit',0))} €</td></tr>"
    passif_rows = ""
    for l in bilan.get("passif", []):
        passif_rows += f"<tr><td>{l.get('compte','')}</td><td>{l.get('libelle','')}</td><td class=\"num\">{_format_montant(l.get('solde_credit',0))} €</td></tr>"

    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>Bilan - {exercice_libelle}</title>{CSS_PRINT}</head><body>
<div class="header"><div><h1>{entreprise}</h1><h2>Bilan — {exercice_libelle}</h2><p>Édité le {date.today().strftime('%d/%m/%Y')}</p></div></div>
<div style="display:flex;gap:40px">
  <div style="flex:1"><h3 style="font-size:12px;color:#1a1a2e;margin-bottom:8px">ACTIF</h3><table><thead><tr><th>Compte</th><th>Libellé</th><th class="num">Montant</th></tr></thead><tbody>
  {actif_rows}
  <tr style="font-weight:bold;border-top:2px solid #1a1a2e"><td colspan="2">Total Actif</td><td class="num">{_format_montant(bilan.get('total_actif',0))} €</td></tr>
  </tbody></table></div>
  <div style="flex:1"><h3 style="font-size:12px;color:#1a1a2e;margin-bottom:8px">PASSIF</h3><table><thead><tr><th>Compte</th><th>Libellé</th><th class="num">Montant</th></tr></thead><tbody>
  {passif_rows}
  <tr style="font-weight:bold;border-top:2px solid #1a1a2e"><td colspan="2">Total Passif</td><td class="num">{_format_montant(bilan.get('total_passif',0))} €</td></tr>
  </tbody></table></div>
</div>
<div class="footer"><p>{entreprise} — SIRET: {params.get('siret','')}</p></div>
</body></html>"""


def template_grand_livre(gl: dict, exercice_libelle: str, params: dict) -> str:
    """Template HTML imprimable pour le grand-livre d'un compte."""
    entreprise = params.get("nom_entreprise", "Mon Entreprise")
    from comptable.plan_comptable import compte_par_numero
    compte = compte_par_numero(gl["compte"])
    libelle = compte.libelle if compte else ""

    rows = ""
    for m in gl["mouvements"]:
        rows += f"""<tr>
          <td>{m['date']}</td><td>{m['journal']}</td><td>{m['piece'] or ''}</td><td>{m['libelle']}</td>
          <td class="num">{_format_montant(m['debit'])}</td><td class="num">{_format_montant(m['credit'])}</td>
          <td class="num">{_format_montant(m['solde_cumul'])}</td></tr>"""

    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>Grand-Livre {gl['compte']}</title>{CSS_PRINT}</head><body>
<div class="header"><div><h1>{entreprise}</h1><h2>Grand-Livre — {gl['compte']} {libelle}</h2><p>{exercice_libelle} — Édité le {date.today().strftime('%d/%m/%Y')}</p></div></div>
{('<p style="font-size:11px;color:#888;margin-bottom:8px">Solde ouverture: ' + _format_montant(gl['solde_ouverture']) + ' €</p>' if gl.get('solde_ouverture') else '')}
<table><thead><tr><th>Date</th><th>Jrnl</th><th>Pièce</th><th>Libellé</th><th class="num">Débit</th><th class="num">Crédit</th><th class="num">Solde</th></tr></thead><tbody>
{rows}
<tr style="font-weight:bold;border-top:2px solid #1a1a2e"><td colspan="4">Totaux / Solde final</td><td class="num">{_format_montant(gl['total_debit'])}</td><td class="num">{_format_montant(gl['total_credit'])}</td><td class="num">{_format_montant(gl['solde_final'])}</td></tr>
</tbody></table>
<div class="footer"><p>{entreprise} — SIRET: {params.get('siret','')}</p></div>
</body></html>"""

def template_resultat(cr, exercice_libelle, params):
    """Template HTML imprimable pour le compte de resultat."""
    entreprise = params.get("nom_entreprise", "Mon Entreprise")
    charges_rows = ""
    for c in cr.get("charges", []):
        charges_rows += f"<tr><td>{c['compte']}</td><td class=\"num\">{_format_montant(c['solde_debit'])}</td></tr>"
    produits_rows = ""
    for p in cr.get("produits", []):
        produits_rows += f"<tr><td>{p['compte']}</td><td class=\"num\">{_format_montant(p['solde_credit'])}</td></tr>"
    resultat = cr.get("resultat_net", 0)
    benefice = cr.get("benefice", False)
    sens = "BENEFICE" if benefice else "PERTE"
    couleur = "#0a8f32" if benefice else "#c0392b"
    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>Compte de Resultat</title>{CSS_PRINT}</head><body>
<div class="header"><div><h1>{entreprise}</h1><h2>Compte de Resultat - {exercice_libelle}</h2><p>Edite le {date.today().strftime('%d/%m/%Y')}</p></div></div>
<h3>CHARGES</h3>
<table><thead><tr><th>Compte</th><th class="num">Montant</th></tr></thead><tbody>{charges_rows}
<tr style="font-weight:bold"><td>Total charges</td><td class="num">{_format_montant(cr.get('total_charges',0))} EUR</td></tr></tbody></table>
<h3 style="margin:20px 0 8px">PRODUITS</h3>
<table><thead><tr><th>Compte</th><th class="num">Montant</th></tr></thead><tbody>{produits_rows}
<tr style="font-weight:bold"><td>Total produits</td><td class="num">{_format_montant(cr.get('total_produits',0))} EUR</td></tr></tbody></table>
<div style="margin-top:20px;text-align:center;padding:12px;background:#f8f8f8">
  <p style="font-size:16px;font-weight:700;color:{couleur}">Resultat net: {_format_montant(resultat)} EUR ({sens})</p>
</div>
<div class="footer"><p>{entreprise}</p></div>
</body></html>"""


def template_budget(budgets, resume, exercice_libelle, params):
    """Template HTML imprimable pour le suivi budgetaire."""
    entreprise = params.get("nom_entreprise", "Mon Entreprise")
    rows = ""
    for b in budgets or []:
        ecart = b.get("ecart", 0)
        pct = b.get("pct_consomme", 0)
        couleur = "#c0392b" if pct > 100 else "#f39c12" if pct > 80 else "#0a8f32"
        rows += f"<tr><td>{b['compte']}</td><td class=\"num\">{_format_montant(b.get('budget',0))}</td><td class=\"num\">{_format_montant(b.get('reel',0))}</td><td class=\"num\" style=\"color:{couleur}\">{_format_montant(ecart)}</td><td class=\"num\">{pct:.0f}%</td></tr>"
    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>Budget</title>{CSS_PRINT}</head><body>
<div class="header"><div><h1>{entreprise}</h1><h2>Suivi Budgetaire - {exercice_libelle}</h2><p>Edite le {date.today().strftime('%d/%m/%Y')}</p></div></div>
<table><thead><tr><th>Compte</th><th class="num">Budget</th><th class="num">Reel</th><th class="num">Ecart</th><th class="num">%</th></tr></thead><tbody>{rows}</tbody></table>
<div class="footer"><p>{entreprise}</p></div>
</body></html>"""

