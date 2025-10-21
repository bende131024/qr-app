import os, json, uuid, io
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, Column, Integer, String, Text
from sqlalchemy.exc import IntegrityError

# ---- Alapbeállítások ----
app = Flask(__name__, template_folder="templates")
DB_PATH = os.environ.get("DATABASE_URL", "sqlite:///adatok.db")
app.config["SQLALCHEMY_DATABASE_URI"] = DB_PATH
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---- Modellek ----
class Adat(db.Model):
    __tablename__ = "adat"
    id = Column(Integer, primary_key=True)
    # régi DB-kben ez lehet, hogy még nincs — indításkor pótoljuk
    azonosito = Column(String(64), unique=True, nullable=True)
    data = Column(Text)

class MetaKV(db.Model):
    __tablename__ = "meta_kv"
    key = Column(String(64), primary_key=True)
    value = Column(Text)

# ---- Segédek ----
def gen_id(n=8):
    return uuid.uuid4().hex[:n].upper()

def ensure_azonosito_column():
    """
    Régi SQLite DB-khez: ha hiányzik az adat.azonosito oszlop, adjuk hozzá,
    töltsük fel a data JSON 'Azonosító' mezőjéből (ha nincs, generáljunk),
    és tegyünk rá egyedi indexet.
    """
    try:
        cols = [r[1] for r in db.session.execute(text("PRAGMA table_info(adat)")).fetchall()]
        if "azonosito" not in cols:
            db.session.execute(text("ALTER TABLE adat ADD COLUMN azonosito TEXT"))
            db.session.commit()

            # kitöltés
            rows = Adat.query.all()
            seen = set()
            for row in rows:
                try:
                    rec = json.loads(row.data or "{}")
                except Exception:
                    rec = {}
                base = str(rec.get("Azonosító", "")).strip().upper()
                if not base:
                    base = gen_id()
                cand = base
                n = 1
                # ütközés ellen
                while cand in seen or db.session.execute(text("SELECT 1 FROM adat WHERE azonosito=:a"), {"a": cand}).fetchone():
                    n += 1
                    cand = f"{base}-{n}"
                row.azonosito = cand
                seen.add(cand)
            db.session.commit()

        # index (ha nincs)
        db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_adat_azonosito ON adat(azonosito)"))
        db.session.commit()
    except Exception:
        db.session.rollback()

def load_meta_defaults():
    """
    Ha még nincs explicit meta, a meglévő sorokból kitaláljuk:
    - mezők listája: Azonosító + a JSON kulcsok
    - legördülők (listak): ha egy mezőnél kevés (<=30) különböző érték van
    """
    mezok = ["Azonosító"]
    listak = {}
    try:
        rows = Adat.query.all()
        for r in rows:
            try:
                rec = json.loads(r.data or "{}")
            except Exception:
                rec = {}
            for k, v in rec.items():
                if k not in mezok:
                    mezok.append(k)
                if k not in listak:
                    listak[k] = set()
                if isinstance(v, str) and v.strip() and len(listak[k]) < 30:
                    listak[k].add(v.strip())
        listak = {k: sorted(list(vs)) for k, vs in listak.items() if vs}
    except Exception:
        pass
    mezok = ["Azonosító"] + [m for m in mezok if m != "Azonosító"]
    return {"mezok": mezok, "listak": listak}

def load_meta():
    """Meta (mezők+listák) kiolvasása a meta_kv táblából; ha üres, fallback a defaults-ra."""
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
    db.session.add(m1)
    db.session.add(m2)
    db.session.commit()

# ---- API: meta ----
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

# ---- API: adatok (desktop szinkron) ----
@app.get("/data")
def data_get():
    meta = load_meta()
    rows = []
    for a in Adat.query.all():
        try:
            rec = json.loads(a.data or "{}")
        except Exception:
            rec = {}
        # biztosítsuk, hogy Azonosító benne legyen
        if "Azonosító" not in rec or not rec["Azonosító"]:
            rec["Azonosító"] = a.azonosito or ""
        rows.append(rec)
    return jsonify({"mezok": meta["mezok"], "listak": meta["listak"], "adatok": rows})

@app.post("/update")
def data_update():
    """
    Desktop app szinkron: inkrementális upsert 'Azonosító' alapján.
    + Meta frissítés (mezők+listák), ha kapunk.
    Várt JSON:
      { "mezok":[...], "listak":{...}, "adatok":[ {..sor..}, ... ] }
    """
    payload = request.get_json(force=True, silent=True) or {}
    mezok = payload.get("mezok")
    listak = payload.get("listak")
    adatok = payload.get("adatok", [])

    if isinstance(mezok, list) and isinstance(listak, dict):
        save_meta(mezok, listak)

    # Upsert rekordok
    for rec in adatok:
        if not isinstance(rec, dict):
            continue
        az = str(rec.get("Azonosító", "")).strip()
        if not az:
            # ha nincs, generálunk
            az = gen_id()
            rec["Azonosító"] = az
        existing = Adat.query.filter_by(azonosito=az).first()
        if existing:
            existing.data = json.dumps(rec, ensure_ascii=False)
        else:
            db.session.add(Adat(azonosito=az, data=json.dumps(rec, ensure_ascii=False)))
    db.session.commit()

    return jsonify({"ok": True})

# ---- /edit/<azonosito> egyszerű szerkesztő ----
@app.route("/edit/<azonosito>", methods=["GET", "POST"])
def edit_row(azonosito):
    row = Adat.query.filter_by(azonosito=azonosito).first()
    if not row:
        abort(404)
    try:
        rec = json.loads(row.data or "{}")
    except Exception:
        rec = {}

    meta = load_meta()
    if request.method == "POST":
        # űrlapból felülírjuk a mezőket
        new_rec = {}
        for f in meta["mezok"]:
            val = request.form.get(f, "")
            if f == "Azonosító":
                val = azonosito
            new_rec[f] = val
        row.data = json.dumps(new_rec, ensure_ascii=False)
        db.session.commit()
        return redirect(url_for("edit_row", azonosito=azonosito))

    return render_template("edit.html", rec=rec, mezok=meta["mezok"], listak=meta["listak"], azonosito=azonosito)

# ---- /qr mobil űrlap + QR kép ----
def generate_unique_id():
    # Rövid, ütközés-védett azonosító
    for _ in range(10):
        cand = gen_id(8)
        if not Adat.query.filter_by(azonosito=cand).first():
            return cand
    return uuid.uuid4().hex.upper()

@app.route("/qr", methods=["GET", "POST"])
def qr_page():
    meta = load_meta()
    if request.method == "POST":
        form = request.form.to_dict()
        az = form.get("Azonosító", "").strip().upper()
        if not az:
            az = generate_unique_id()
        # rekord összeállítás
        rec = {}
        for f in meta["mezok"]:
            if f == "Azonosító":
                rec[f] = az
            else:
                rec[f] = form.get(f, "")
        # mentés/upsert
        row = Adat.query.filter_by(azonosito=az).first()
        if row:
            row.data = json.dumps(rec, ensure_ascii=False)
        else:
            db.session.add(Adat(azonosito=az, data=json.dumps(rec, ensure_ascii=False)))
        db.session.commit()
        return render_template("qr.html", mezok=meta["mezok"], listak=meta["listak"], created=az)
    else:
        return render_template("qr.html", mezok=meta["mezok"], listak=meta["listak"], created=None)

@app.route("/qrimg/<azonosito>.png")
def qr_image(azonosito):
    # QR a szerkesztő oldalra mutasson
    try:
        import qrcode
    except Exception:
        abort(500, "qrcode csomag nincs telepítve (pip install qrcode Pillow)")
    edit_url = url_for("edit_row", azonosito=azonosito, _external=True)
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(edit_url); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png")

# ---- Főfüggvény ----
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_azonosito_column()   # régi DB-k javítása
    # PROD-on gunicorn indítja; fejlesztésben:
    app.run(host="0.0.0.0", port=5000)
