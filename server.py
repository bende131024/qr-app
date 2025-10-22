# server.py — Flask + SQLAlchemy backend a QR apphoz
import os, io, json, uuid
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, Column, Integer, String, Text, inspect

# -------------------- Flask & DB --------------------
app = Flask(__name__, template_folder="templates")

# DATABASE_URL normalizálás (Render/Postgres), fallback: helyi SQLite
db_url = os.environ.get("DATABASE_URL", "sqlite:///adatok.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# -------------------- Modellek --------------------
class Adat(db.Model):
    __tablename__ = "adat"
    id = Column(Integer, primary_key=True)
    azonosito = Column(String(64), unique=True, nullable=True)  # régi DB-kben hiányozhat, pótoljuk
    data = Column(Text)                                         # JSON szöveg
    deleted = Column(Integer, default=0)                        # 0=aktív, 1=törölt (soft delete)

class MetaKV(db.Model):
    __tablename__ = "meta_kv"
    key = Column(String(64), primary_key=True)
    value = Column(Text)

# -------------------- Segédek --------------------
def gen_id(n=8) -> str:
    return uuid.uuid4().hex[:n].upper()

def is_all_empty_except_id(rec: dict) -> bool:
    """True, ha az Azonosítón kívül minden mező üres/None."""
    for k, v in rec.items():
        if k == "Azonosító":
            continue
        if isinstance(v, str):
            if v.strip():
                return False
        elif v not in (None, "", []):
            return False
    return True

def ensure_schema():
    """
    Táblák létrehozása + hiányzó oszlopok pótlása (SQLite/Postgres kompatibilis),
    egyedi index az azonosítóra; régi sorok azonosítójának feltöltése.
    """
    db.create_all()
    insp = inspect(db.engine)
    tables = set(insp.get_table_names())
    if "adat" not in tables or "meta_kv" not in tables:
        db.create_all()
        insp = inspect(db.engine)
        tables = set(insp.get_table_names())

    # oszlopok lekérdezése az 'adat' tábláról
    cols = {c["name"] for c in insp.get_columns("adat")}

    # ALTER-ek tranzakcióban
    with db.engine.begin() as conn:
        if "azonosito" not in cols:
            conn.execute(text("ALTER TABLE adat ADD COLUMN azonosito TEXT"))
        if "deleted" not in cols:
            # mindkét dialektus érti ezt a szintaxist
            conn.execute(text("ALTER TABLE adat ADD COLUMN deleted INTEGER DEFAULT 0"))
        # index az azonosítóra
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_adat_azonosito ON adat(azonosito)"))

    # régi sorok azonosítójának feltöltése + deleted alapérték
    rows = Adat.query.all()
    for row in rows:
        if not getattr(row, "azonosito", None):
            try:
                rec = json.loads(row.data or "{}")
            except Exception:
                rec = {}
            base = (rec.get("Azonosító") or "").strip().upper() or gen_id()
            cand = base
            n = 1
            # ütközés esetén sorszámozzuk
            while Adat.query.filter_by(azonosito=cand).first():
                n += 1
                cand = f"{base}-{n}"
            row.azonosito = cand
        if row.deleted is None:
            row.deleted = 0
    db.session.commit()

def load_meta_defaults():
    """Ha nincs mentett meta, a meglévő aktív rekordokból képezünk mezőlistát és legördülő javaslatokat."""
    mezok = ["Azonosító"]
    listak = {}
    try:
        for a in Adat.query.filter_by(deleted=0).all():
            try:
                rec = json.loads(a.data or "{}")
            except Exception:
                rec = {}
            for k, v in rec.items():
                if k not in mezok:
                    mezok.append(k)
                if isinstance(v, str):
                    if k not in listak:
                        listak[k] = set()
                    if v.strip() and len(listak[k]) < 50:
                        listak[k].add(v.strip())
        listak = {k: sorted(list(vs)) for k, vs in listak.items() if vs}
    except Exception:
        pass
    # Azonosító mindig első
    mezok = ["Azonosító"] + [m for m in mezok if m != "Azonosító"]
    return {"mezok": mezok, "listak": listak}

def load_meta():
    """Mentett meta beolvasása, különben default generálása."""
    out = {"mezok": [], "listak": {}}
    try:
        m1 = MetaKV.query.get("mezok")
        m2 = MetaKV.query.get("listak")
        if m1 and m1.value:
            out["mezok"] = json.loads(m1.value)
        if m2 and m2.value:
            out["listak"] = json.loads(m2.value)
    except Exception:
        pass
    if not out["mezok"]:
        out = load_meta_defaults()
    out["mezok"] = ["Azonosító"] + [m for m in out["mezok"] if m != "Azonosító"]
    return out

def save_meta(mezok, listak):
    m1 = MetaKV.query.get("mezok") or MetaKV(key="mezok")
    m2 = MetaKV.query.get("listak") or MetaKV(key="listak")
    m1.value = json.dumps(mezok, ensure_ascii=False)
    m2.value = json.dumps(listak, ensure_ascii=False)
    db.session.add(m1); db.session.add(m2); db.session.commit()

# -------------------- Meta endpointok --------------------
@app.get("/meta")
def meta_get():
    return jsonify(load_meta())

@app.post("/meta")
def meta_post():
    data = request.get_json(force=True, silent=True) or {}
    mezok = data.get("mezok")
    listak = data.get("listak")
    if not isinstance(mezok, list) or not isinstance(listak, dict):
        return jsonify({"ok": False, "error": "Adj meg 'mezok' listát és 'listak' szótárt."}), 400
    save_meta(mezok, listak)
    return jsonify({"ok": True})

# -------------------- Adat endpointok --------------------
@app.get("/data")
def data_get():
    """Aktív sorok + meta JSON-ben (desktop app ezt hívja)."""
    meta = load_meta()
    rows = []
    for a in Adat.query.filter_by(deleted=0).all():
        try:
            rec = json.loads(a.data or "{}")
        except Exception:
            rec = {}
        rec.setdefault("Azonosító", a.azonosito or "")
        rows.append(rec)
    return jsonify({"mezok": meta["mezok"], "listak": meta["listak"], "adatok": rows})

@app.post("/update")
def data_update():
    """
    Desktop szinkron / upsert.
    Body: {"mezok":[...], "listak":{...}, "adatok":[{...}, ...]}
    - mezok/listak mentése (ha megadva),
    - adatok upsert Azonosító szerint (üres rekordokat kihagyjuk),
    - törlés NEM történik itt (ahhoz /delete).
    """
    payload = request.get_json(force=True, silent=True) or {}
    mezok = payload.get("mezok")
    listak = payload.get("listak")
    adatok = payload.get("adatok", [])

    if isinstance(mezok, list) and isinstance(listak, dict):
        save_meta(mezok, listak)

    upserted = 0
    for rec in adatok:
        if not isinstance(rec, dict):
            continue
        # ha minden üres az Azonosítón kívül → ne tároljuk
        if is_all_empty_except_id(rec):
            continue

        az = (rec.get("Azonosító") or "").strip() or gen_id()
        rec["Azonosító"] = az

        row = Adat.query.filter_by(azonosito=az).first()
        if row:
            row.data = json.dumps(rec, ensure_ascii=False)
            row.deleted = 0
        else:
            db.session.add(Adat(azonosito=az, data=json.dumps(rec, ensure_ascii=False), deleted=0))
        upserted += 1

    db.session.commit()
    return jsonify({"ok": True, "upserted": upserted})

@app.post("/delete")
def delete_bulk():
    """
    Soft delete: {"azonositok": ["ID1","ID2",...]}
    Desktopból így küldjük, hogy szinkronnál ne jöjjenek vissza.
    """
    payload = request.get_json(force=True, silent=True) or {}
    ids = payload.get("azonositok", [])
    if not isinstance(ids, list):
        return jsonify({"ok": False, "error": "Adj meg 'azonositok' listát."}), 400
    cnt = 0
    for az in ids:
        row = Adat.query.filter_by(azonosito=str(az)).first()
        if row and row.deleted != 1:
            row.deleted = 1
            cnt += 1
    db.session.commit()
    return jsonify({"ok": True, "deleted": cnt})

@app.post("/delete/<azonosito>")
def delete_one(azonosito):
    row = Adat.query.filter_by(azonosito=azonosito).first()
    if not row:
        abort(404)
    row.deleted = 1
    db.session.commit()
    # JSON kérésre JSON válasz
    if request.is_json or request.headers.get("Accept","").startswith("application/json"):
        return jsonify({"ok": True})
    return redirect(url_for("qr_page"))

# -------------------- QR / Edit oldalak --------------------
@app.route("/qr", methods=["GET", "POST"])
def qr_page():
    """
    Mobilbarát űrlap új tételhez. Üres beküldésre nem hoz létre rekordot.
    Siker esetén 'created' változóval renderel (QR megjelenítés).
    """
    meta = load_meta()
    msg = None
    created = None

    if request.method == "POST":
        form = request.form.to_dict()
        az = (form.get("Azonosító") or "").strip().upper() or gen_id()

        rec = {}
        for f in meta["mezok"]:
            if f == "Azonosító":
                rec[f] = az
            else:
                rec[f] = form.get(f, "")

        if is_all_empty_except_id(rec):
            msg = "Nem jött létre tétel: nem adtál meg adatot."
            return render_template("qr.html", mezok=meta["mezok"], listak=meta["listak"], created=None, msg=msg)

        row = Adat.query.filter_by(azonosito=az).first()
        if row:
            row.data = json.dumps(rec, ensure_ascii=False)
            row.deleted = 0
        else:
            db.session.add(Adat(azonosito=az, data=json.dumps(rec, ensure_ascii=False), deleted=0))
        db.session.commit()
        created = az

    return render_template("qr.html", mezok=meta["mezok"], listak=meta["listak"], created=created, msg=msg)

@app.route("/edit/<azonosito>", methods=["GET", "POST"])
def edit_row(azonosito):
    """
    Tétel szerkesztése. Törlés gomb POST-tal (delete=1) soft delete-re állítja.
    """
    row = Adat.query.filter_by(azonosito=azonosito, deleted=0).first()
    if not row:
        abort(404)

    try:
        rec = json.loads(row.data or "{}")
    except Exception:
        rec = {}

    meta = load_meta()

    if request.method == "POST":
        # Törlés?
        if request.form.get("delete") == "1":
            row.deleted = 1
            db.session.commit()
            return redirect(url_for("qr_page"))

        # Mentés
        new_rec = {}
        for f in meta["mezok"]:
            if f == "Azonosító":
                new_rec[f] = azonosito
            else:
                new_rec[f] = request.form.get(f, "")

        # üres rekordot ne tartsuk meg
        if is_all_empty_except_id(new_rec):
            row.deleted = 1
        else:
            row.data = json.dumps(new_rec, ensure_ascii=False)
            row.deleted = 0
        db.session.commit()
        return redirect(url_for("edit_row", azonosito=azonosito))

    return render_template("edit.html", rec=rec, mezok=meta["mezok"], listak=meta["listak"], azonosito=azonosito)

@app.route("/qrimg/<azonosito>.png")
def qr_image(azonosito):
    """PNG QR a /edit/<azonosito> linkre."""
    try:
        import qrcode
    except Exception:
        abort(500, "qrcode csomag nincs telepítve (pip install qrcode Pillow)")
    edit_url = url_for("edit_row", azonosito=azonosito, _external=True)
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(edit_url); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    bio = io.BytesIO(); img.save(bio, format="PNG"); bio.seek(0)
    return send_file(bio, mimetype="image/png")

# -------------------- Diagnosztika --------------------
@app.get("/_health")
def _health():
    try:
        Adat.query.limit(1).all()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

# -------------------- Boot: séma biztosítása importkor --------------------
with app.app_context():
    try:
        ensure_schema()
    except Exception as e:
        app.logger.exception("ensure_schema() failed on boot: %s", e)

# -------------------- Fejlesztői futtatás --------------------
if __name__ == "__main__":
    # Fejlesztéshez (Renderen gunicorn indítja: 'gunicorn server:app')
    app.run(host="0.0.0.0", port=5000)
