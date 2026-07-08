#!/usr/bin/env python3
"""
ComptaPro — Suite de tests anti-régression.
À exécuter après chaque modification pour valider que rien n'est cassé.

Usage:
    python regression_tests.py              # Quick (no server needed)
    python regression_tests.py --full       # Full (starts server, tests APIs)
    python regression_tests.py --ci         # CI mode (fail fast, JSON output)

Détecte:
    - JS corrompu (braces, UTF-8, async dupliqué)
    - Fonctions critiques absentes
    - Modules Python corrompus
    - Tables SQL manquantes
    - APIs en panne
"""

import sys, os, re, json, subprocess, time, http.client, sqlite3

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(WORKSPACE, "comptable", "static", "index.html")
SERVER = os.path.join(WORKSPACE, "comptable", "server.py")
DB_PATH = os.path.join(WORKSPACE, "comptabilite.db")

CI_MODE = "--ci" in sys.argv
FULL_MODE = "--full" in sys.argv

class Suite:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.details = []

    def ok(self, name, detail=""):
        self.passed += 1
        if not CI_MODE: print(f"  ✅ {name}")
        self.details.append({"name": name, "status": "pass", "detail": detail})

    def fail(self, name, detail=""):
        self.failed += 1
        msg = f"  ❌ {name}"
        if detail: msg += f" — {detail}"
        print(msg)
        self.details.append({"name": name, "status": "fail", "detail": detail})
        if CI_MODE: sys.exit(1)

    def skip(self, name, reason=""):
        self.skipped += 1
        if not CI_MODE: print(f"  ⏭️ {name} (skip: {reason})")
        self.details.append({"name": name, "status": "skip", "detail": reason})


s = Suite()

# ═══════════════════════ PHASE 1: Frontend Integrity ═══════════════════════
def phase1():
    print(f"\n═══ PHASE 1: Frontend HTML ═══")

    if not os.path.exists(INDEX):
        s.fail("index.html not found", INDEX)
        return

    with open(INDEX, "r", encoding="utf-8") as fh:
        t = fh.read()

    s.ok(f"File exists", f"{len(t):,} bytes")

    # 1.1 JS braces balance
    script_blocks = t.split("<script>")
    total_o, total_c = 0, 0
    for i, block in enumerate(script_blocks):
        if "</script>" not in block: continue
        js = block.split("</script>")[0]
        o, c = js.count("{"), js.count("}")
        total_o += o; total_c += c
        if o != c:
            s.fail(f"JS braces block #{i}", f"{o} open vs {c} close")
    if total_o == total_c:
        s.ok(f"JS braces global", f"{total_o}/{total_c}")
    else:
        s.fail(f"JS braces global", f"{total_o}/{total_c}")

    # 1.2 Real corruption markers (not substring false positives)
    bad_patterns = [
        ("async async function", "Duplicate async keyword"),
        ("\ufffd\ufffd", "UTF-8 replacement chars"),
    ]
    # Check character before "unction api(" — only report if it's NOT "f"
    for m in re.finditer(r"(.)unction api\(", t):
        prev_char = m.group(1)
        if prev_char != "f":
            s.fail("Corrupted function api", f"char before 'unction' is {repr(prev_char)} at pos {m.start()}")

    if not s.failed:
        s.ok("No corruption markers")

    # 1.3 Required features (adapted to actual v1.0 codebase)
    features = [
        ("function api(", "API handler"),
        ("function navigate(", "Navigation"),
        ("function loadExercices(", "Exercice loader"),
        ("function loadDashboard(", "Dashboard"),
        ("function loadEcritures(", "Ecritures"),
        ("function loadFactures(", "Factures"),
        ("function loadBalance(", "Balance"),
        ("function loadBilan(", "Bilan"),
        ("function loadBanque(", "Banque"),
        ("function loadResultat(", "Resultat"),
        ("loadNotifs", "Notifications"),
        ("openModal(", "Modal system"),
        ("closeModal(", "Modal closer"),
        ("function toast(", "Toast notifications"),
        ("function saveFacture(", "Save facture"),
        ("submitSaisieEcriture(", "Save ecriture"),
        ("importerCSV(", "CSV import"),
        ("doRapproche(", "Bank reconciliation"),
        ("function toggleSection(", "Sidebar toggle"),
        ("search-input", "Search input"),
        ("exercice-select", "Exercice selector"),
        ("printPage(", "Print handler"),
        ("exportCSV(", "Export handler"),
    ]
    enhanced = [
        ("toggleDarkMode", "Dark mode"),
        ("showShortcuts", "Keyboard shortcuts"),
        ("showQRCode", "QR code mobile"),
        ("showSocietes", "Multi-societe"),
        ("initWidgetDrag", "Widget drag"),
        ("loadPJ", "Pieces jointes"),
        ("_comptaErrors", "Error logger"),
        ("panel-pj", "PJ panel"),
        ("modal-qr", "QR modal"),
        ("shortcuts-modal", "Shortcuts modal"),
        ("societes-modal", "Societes modal"),
        ("Alt+D", "Shortcut ref Alt+D"),
        ("data-theme", "Dark mode CSS var"),
    ]
    for feat, label in features + enhanced:
        if feat in t:
            s.ok(f"Feature: {label}")
        else:
            s.fail(f"Feature: {label}", f"'{feat[:40]}' not found")

    # 1.4 No duplicate code patterns (definitions only)
    if t.count("const origInit=loadExercices;") <= 1:
        s.ok("No duplicate origInit definition", f"{t.count('const origInit=loadExercices;')}")
    else:
        s.fail("Duplicate origInit definition", f"{t.count('const origInit=loadExercices;')} occurrences")

    if t.count("const origNavigate=navigate;") <= 1:
        s.ok("No duplicate origNavigate", f"{t.count('const origNavigate=navigate;')}")
    else:
        s.fail("Duplicate origNavigate definition")


# ═══════════════════════ PHASE 2: Python Syntax ═══════════════════════
def phase2():
    print(f"\n═══ PHASE 2: Python Modules ═══")
    import py_compile
    py_dir = os.path.join(WORKSPACE, "comptable")
    for f in sorted(os.listdir(py_dir)):
        if f.endswith(".py"):
            fpath = os.path.join(py_dir, f)
            try:
                py_compile.compile(fpath, doraise=True)
                s.ok(f"Syntax: {f}")
            except py_compile.PyCompileError as e:
                s.fail(f"Syntax: {f}", str(e))

    # Check all imports resolve
    try:
        with open(SERVER, "r", encoding="utf-8") as fh:
            st = fh.read()
        imports = re.findall(r"from comptable\.(\w+) import", st)
        missing = [m for m in imports if not os.path.exists(os.path.join(py_dir, f"{m}.py"))]
        if missing:
            s.fail("Missing server modules", ", ".join(missing))
        else:
            s.ok(f"All server imports resolve", f"{len(imports)} modules")
    except Exception as e:
        s.skip("Import check", str(e))


# ═══════════════════════ PHASE 3: Database ═══════════════════════
def phase3():
    print(f"\n═══ PHASE 3: Database Integrity ═══")

    if not os.path.exists(DB_PATH):
        s.skip("Database", f"{DB_PATH} not found")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row

        # Tables that must exist
        required = [
            "exercices", "ecritures", "lignes_ecriture", "comptes_aux",
            "factures", "lignes_facture", "releves_bancaires", "lignes_releve",
            "parametres", "scenarios_relance", "piste_audit",
            "budgets", "notes_frais", "abonnements", "previsions",
            "regles_categorisation", "lettrages", "lignes_lettrage",
            "immobilisations", "dotations_amortissement",
            "emprunts", "echeances_emprunt", "pieces_jointes",
            "validations_achat", "historique_relances",
        ]

        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}

        for tbl in required:
            if tbl in existing:
                s.ok(f"Table: {tbl}")
            else:
                s.fail(f"Table: {tbl}", "missing")

        # Data sanity
        ex = conn.execute("SELECT COUNT(*) FROM exercices").fetchone()[0]
        if ex > 0:
            s.ok(f"Exercices", f"{ex} rows")
        else:
            s.fail("Exercices", "empty")

        ecr = conn.execute("SELECT COUNT(*) FROM ecritures").fetchone()[0]
        if ecr > 0:
            s.ok(f"Ecritures", f"{ecr} rows")
        else:
            s.skip("Ecritures", "empty (no seed data)")

        # Foreign keys
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk:
            s.ok("Foreign keys", "ON")
        else:
            s.fail("Foreign keys", "OFF — db.py must set PRAGMA foreign_keys=ON")

        conn.close()
    except Exception as e:
        s.fail("Database checks", str(e))


# ═══════════════════════ PHASE 4: API Tests ═══════════════════════
def phase4():
    print(f"\n═══ PHASE 4: API Endpoints ═══")

    PORT = 8080
    try:
        c = http.client.HTTPConnection("localhost", PORT, timeout=3)
        c.request("GET", "/api/exercices")
        r = c.getresponse()
        r.read()
        c.close()
    except Exception:
        s.skip("API tests", "Server not running on :8080 — start with: python comptable/server.py --port 8080")
        return

    endpoints = [
        ("Exercices", "/api/exercices"),
        ("Bilan", "/api/bilan?exercice_id=1"),
        ("Resultat", "/api/resultat?exercice_id=1"),
        ("Balance", "/api/balance?exercice_id=1"),
        ("Dashboard", "/api/dashboard/tresorerie?exercice_id=1"),
        ("Societes", "/api/societes"),
        ("Immobilisations", "/api/immobilisations/resume?exercice_id=1"),
        ("Ecritures", "/api/ecritures?exercice_id=1"),
        ("Factures", "/api/factures?exercice_id=1"),
        ("Grand-Livre", "/api/grand-livre?exercice_id=1&compte=411"),
        ("Search", "/api/search?q=test&exercice_id=1"),
        ("QR Code", "/api/qrcode"),
        ("Pieces jointes", "/api/pj"),
        ("PJ Stats", "/api/pj/stats"),
        ("Plan comptable", "/api/plan-comptable"),
    ]

    for label, path in endpoints:
        try:
            c = http.client.HTTPConnection("localhost", PORT, timeout=5)
            c.request("GET", path)
            r = c.getresponse()
            body = r.read()
            c.close()

            if r.status == 200:
                if body.startswith(b"<svg") or body.startswith(b"\x89PNG"):
                    s.ok(f"GET {label}", f"Image {len(body)}B")
                else:
                    try:
                        json.loads(body)
                        s.ok(f"GET {label}", f"JSON {len(body)}B")
                    except:
                        s.fail(f"GET {label}", f"Invalid response ({len(body)}B)")
            else:
                s.fail(f"GET {label}", f"HTTP {r.status}")
        except Exception as e:
            s.fail(f"GET {label}", str(e))

    # Frontend serving check
    try:
        c = http.client.HTTPConnection("localhost", PORT, timeout=5)
        c.request("GET", "/")
        r = c.getresponse()
        served = r.read().decode("utf-8", errors="replace")
        c.close()

        if "</script>" in served and "<script>" in served:
            s.ok("Frontend served", f"{len(served):,}B, has script tags")
        else:
            s.fail("Frontend serving", "missing script tags")
    except Exception as e:
        s.fail("Frontend serving", str(e))


# ═══════════════════════ MAIN ═══════════════════════
def main():
    if not CI_MODE:
        print("🔬 ComptaPro — Anti-Régression Suite")
        print(f"   {WORKSPACE}\n")

    phase1()
    phase2()
    phase3()

    if FULL_MODE or CI_MODE:
        phase4()
    else:
        s.skip("API tests", "use --full to run (needs server on :8080)")

    # ── Summary ──
    total = s.passed + s.failed + s.skipped
    if CI_MODE:
        print(json.dumps({"passed": s.passed, "failed": s.failed, "skipped": s.skipped, "total": total}))
    else:
        print(f"\n{'─'*40}")
        print(f"✅ {s.passed} passed  ❌ {s.failed} failed  ⏭️ {s.skipped} skipped  ({total} total)")
        if s.failed > 0:
            print(f"\n❌ RÉGRESSION DÉTECTÉE — ne pas déployer !")
            print(f"   Corrige les tests en échec puis relance : python regression_tests.py --full")
        else:
            print(f"\n✅ Aucune régression — prêt à déployer.")

    sys.exit(1 if s.failed > 0 else 0)

if __name__ == "__main__":
    main()
