"""
Pièces jointes — module de gestion des justificatifs (tickets de caisse, factures scannees, etc.)
Stocke les images en BLOB + metadonnees dans la base.

ponytail: simple blob storage, no OCR. Upgrade path: OCR via external API option.
"""

import os
import time
import hashlib
import base64
import secrets
from datetime import datetime
from typing import Optional, List
from comptable.db import get_db

DB = get_db

# Token temporaires pour le mobile bridge (validite 30 min)
_mobile_tokens = {}  # token -> (created_at, ip)


def _cleanup_tokens():
    """Supprime les tokens expires (> 30 min)."""
    now = time.time()
    expired = [t for t, (ts, _) in _mobile_tokens.items() if now - ts > 1800]
    for t in expired:
        del _mobile_tokens[t]


def generate_mobile_token(host: str) -> str:
    """Genere un token unique pour la liaison mobile."""
    _cleanup_tokens()
    token = secrets.token_urlsafe(16)
    _mobile_tokens[token] = (time.time(), host)
    return token


def validate_mobile_token(token: str) -> bool:
    """Valide un token mobile (non expire)."""
    _cleanup_tokens()
    return token in _mobile_tokens


def get_mobile_url(host: str) -> str:
    """Genere l'URL mobile complete avec token."""
    token = generate_mobile_token(host)
    return f"http://{host}/mobile/upload?token={token}"


def init_pj_db(conn=None):
    """Initialise la table des pieces jointes."""
    if conn is None:
        conn = DB()
        close_conn = True
    else:
        close_conn = False
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pieces_jointes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nom         TEXT NOT NULL,
            type_mime   TEXT NOT NULL DEFAULT 'image/jpeg',
            taille      INTEGER NOT NULL DEFAULT 0,
            date_prise  TEXT,
            categorie   TEXT DEFAULT 'ticket',
            ecriture_id INTEGER REFERENCES ecritures(id),
            facture_id  INTEGER REFERENCES factures(id),
            note_id     INTEGER REFERENCES notes_frais(id),
            tags        TEXT DEFAULT '',
            fichier     BLOB,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_pj_ecriture ON pieces_jointes(ecriture_id);
        CREATE INDEX IF NOT EXISTS idx_pj_facture ON pieces_jointes(facture_id);
        CREATE INDEX IF NOT EXISTS idx_pj_categorie ON pieces_jointes(categorie);
    """)
    if close_conn:
        conn.close()


def ajouter_pj(nom: str, data: bytes, type_mime: str = "image/jpeg",
               categorie: str = "ticket", date_prise: str = None,
               tags: str = "") -> dict:
    """Ajoute une piece jointe. Retourne l'objet cree."""
    conn = DB()
    taille = len(data)
    if date_prise is None:
        date_prise = datetime.now().strftime("%Y-%m-%d")
    c = conn.execute(
        """INSERT INTO pieces_jointes (nom, type_mime, taille, date_prise, categorie, fichier, tags)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (nom, type_mime, taille, date_prise, categorie, data, tags)
    )
    pj_id = c.lastrowid
    conn.commit()
    r = conn.execute("SELECT * FROM pieces_jointes WHERE id=?", (pj_id,)).fetchone()
    conn.close()
    return _pj_dict(r)


def lister_pj(categorie: str = None, ecriture_id: int = None,
              facture_id: int = None, date_debut: str = None,
              date_fin: str = None, offset: int = 0, limit: int = 50) -> dict:
    """Liste les pieces jointes avec pagination."""
    conn = DB()
    where = []
    params = []
    if categorie:
        where.append("categorie=?")
        params.append(categorie)
    if ecriture_id:
        where.append("ecriture_id=?")
        params.append(ecriture_id)
    if facture_id:
        where.append("facture_id=?")
        params.append(facture_id)
    if date_debut:
        where.append("date_prise>=?")
        params.append(date_debut)
    if date_fin:
        where.append("date_prise<=?")
        params.append(date_fin)

    w = ("WHERE " + " AND ".join(where)) if where else ""
    count = conn.execute(f"SELECT COUNT(*) FROM pieces_jointes {w}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM pieces_jointes {w} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset]
    ).fetchall()
    conn.close()
    return {
        "total": count,
        "offset": offset,
        "limit": limit,
        "items": [_pj_dict(r, include_fichier=False) for r in rows]
    }


def get_pj(pj_id: int) -> Optional[dict]:
    """Recupere une piece jointe complete (avec fichier)."""
    conn = DB()
    r = conn.execute("SELECT * FROM pieces_jointes WHERE id=?", (pj_id,)).fetchone()
    conn.close()
    if r:
        return _pj_dict(r, include_fichier=True)
    return None


def get_pj_fichier(pj_id: int) -> Optional[tuple]:
    """Recupere le fichier binaire et le type MIME."""
    conn = DB()
    r = conn.execute(
        "SELECT fichier, type_mime, nom FROM pieces_jointes WHERE id=?",
        (pj_id,)
    ).fetchone()
    conn.close()
    if r:
        return (r["fichier"], r["type_mime"], r["nom"])
    return None


def lier_pj(pj_id: int, ecriture_id: int = None, facture_id: int = None,
            note_id: int = None, categorie: str = None, tags: str = None):
    """Lie une piece jointe a une ecriture/facture/note."""
    conn = DB()
    sets = []
    params = []
    if ecriture_id is not None:
        sets.append("ecriture_id=?")
        params.append(ecriture_id)
    if facture_id is not None:
        sets.append("facture_id=?")
        params.append(facture_id)
    if note_id is not None:
        sets.append("note_id=?")
        params.append(note_id)
    if categorie is not None:
        sets.append("categorie=?")
        params.append(categorie)
    if tags is not None:
        sets.append("tags=?")
        params.append(tags)
    if sets:
        params.append(pj_id)
        conn.execute(
            f"UPDATE pieces_jointes SET {', '.join(sets)} WHERE id=?",
            params
        )
        conn.commit()
    conn.close()


def supprimer_pj(pj_id: int):
    """Supprime une piece jointe."""
    conn = DB()
    conn.execute("DELETE FROM pieces_jointes WHERE id=?", (pj_id,))
    conn.commit()
    conn.close()


def stats_pj() -> dict:
    """Statistiques des pieces jointes."""
    conn = DB()
    total = conn.execute("SELECT COUNT(*) FROM pieces_jointes").fetchone()[0]
    par_cat = conn.execute(
        "SELECT categorie, COUNT(*) as n FROM pieces_jointes GROUP BY categorie ORDER BY n DESC"
    ).fetchall()
    non_liees = conn.execute(
        "SELECT COUNT(*) FROM pieces_jointes WHERE ecriture_id IS NULL AND facture_id IS NULL"
    ).fetchone()[0]
    recentes = conn.execute(
        "SELECT COUNT(*) FROM pieces_jointes WHERE created_at >= datetime('now','-7 days')"
    ).fetchone()[0]
    conn.close()
    return {
        "total": total,
        "non_liees": non_liees,
        "recentes_7j": recentes,
        "par_categorie": [{"categorie": r["categorie"], "nombre": r["n"]} for r in par_cat]
    }


def _pj_dict(row, include_fichier: bool = False) -> dict:
    """Convertit une ligne SQL en dict JSON."""
    if not row:
        return None
    d = {
        "id": row["id"],
        "nom": row["nom"],
        "type_mime": row["type_mime"],
        "taille": row["taille"],
        "date_prise": row["date_prise"],
        "categorie": row["categorie"],
        "ecriture_id": row["ecriture_id"],
        "facture_id": row["facture_id"],
        "note_id": row["note_id"],
        "tags": row["tags"],
        "created_at": row["created_at"],
    }
    if include_fichier and row["fichier"]:
        d["fichier_base64"] = base64.b64encode(row["fichier"]).decode("ascii")
    elif row["fichier"]:
        d["has_fichier"] = True
    else:
        d["has_fichier"] = False
    return d


def handle_upload(environ, upload_dir: str = None) -> dict:
    """
    Traite un upload multipart/form-data depuis le WSGI environ.
    Stdlib uniquement : utilise cgi.FieldStorage.
    Retourne le resultat de l'upload.
    """
    import io
    import cgi
    
    content_type = environ.get("CONTENT_TYPE", "")
    content_length = int(environ.get("CONTENT_LENGTH", 0))
    
    if not content_type.startswith("multipart/form-data"):
        raise ValueError("Content-Type must be multipart/form-data")
    
    body = environ["wsgi.input"].read(content_length) if "wsgi.input" in environ else b""
    
    # Parse multipart manually using email.parser (stdlib)
    from email.parser import BytesParser
    from email.policy import default
    
    boundary = content_type.split("boundary=")[1].strip('"')
    raw = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    
    # Use cgi.FieldStorage with BytesIO
    fp = io.BytesIO(body)
    env = {
        "REQUEST_METHOD": "POST",
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(content_length),
    }
    form = cgi.FieldStorage(fp=fp, environ=env, keep_blank_values=True)
    
    files = []
    errors = []
    
    if isinstance(form, cgi.FieldStorage) and form.list:
        for item in form.list:
            if hasattr(item, "filename") and item.filename:
                data = item.file.read()
                nom = item.filename or "scan.jpg"
                mime = item.type or "image/jpeg"
                if not data:
                    errors.append(f"{nom}: fichier vide")
                    continue
                
                # Categorie depuis le champ du form
                categorie = form.getfirst("categorie", "ticket")
                date_prise = form.getfirst("date_prise", datetime.now().strftime("%Y-%m-%d"))
                tags = form.getfirst("tags", "")
                
                pj = ajouter_pj(nom, data, mime, categorie, date_prise, tags)
                files.append(pj)
    
    return {
        "success": len(errors) == 0,
        "uploaded": len(files),
        "files": files,
        "errors": errors,
    }
