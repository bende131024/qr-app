import os, json, uuid, io
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, Column, Integer, String, Text
from sqlalchemy.exc import IntegrityError

app = Flask(__name__, template_folder="templates")
DB_PATH = os.environ.get("DATABASE_URL", "sqlite:///adatok.db")
app.config["SQLALCHEMY_DATABASE_URI"] = DB_PATH
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ======= MODELL =======
class Adat(db.Model):
    __tablename__ = "adat"
    id = Column(Integer, primary_key=True)
    azonosito = Column(String(64), unique=True, nullable=True)
    data = Column(Text)
    deleted = Column(Integer, default=0)  # 0 = aktív, 1 = törölt

class MetaKV(db.Model):
    __tablename__ = "meta_kv"
    key = Column(String(64), primary_key=True)
    value = Column(Text)

# ======= SEGÉDEK =======
def gen_id(n=8):
    return uuid.uuid4().hex[:n].upper()

def ensure_schema():
    """ régi DB-khez: pótolja a hiányzó oszlopokat + indexeket """
    try:
        cols = [r[1] for r in db.session.execute(text("PRAGMA table_info(adat)")).fetchall()]
        if "azonosito" not in cols:
            db.session.execute(text("ALTER TABLE adat ADD COLUMN azonosito TEXT"))
            db.session.commit()
            rows = Adat.query.all()
            seen = set()
            for row in rows:
                try:
                    rec = json.loads(row.data or "{}")
                except Exception:
                    rec = {}
                base = str(rec.get("Azonosító", "")).strip().upper() or gen_id()
                cand = base; n = 1
                while cand in seen or db.session.execute(text("SELECT 1 FROM adat WHERE azonosito=:a"), {"a": cand}).fetchone():
                    n += 1
                    cand = f"{base}-{n}"
                row.azonosito = cand
                seen.add(cand)
            db.session.commit()
        if "deleted" not in cols:
            db.session.execute(text("ALTER TABLE adat ADD COLUMN deleted INTEGER DEFAULT 0"))
            db.session.commit()
        db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_adat_azonosito ON adat(azonosito)"))
        db.session.commit()
    except Exception:
        db.session.rollback()

def load_meta_defaults():
    mezok = ["Azonosító"]
    listak = {}
    try:
        for r in Adat.query.filter_by(deleted=0).all():
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

def is_all_empty_except_id(rec: dict):
    for k, v in rec.items():
        if k == "Azonosító": 
            continue
        if isinstance(v, str) and v.strip():
            return False
        if v not in (None, "", []):
            return False
    return True

# ======= META ENDPOINTOK =======
@app.get("/meta")
def meta_get():
    return jsonify(load_meta())

@app.post("/meta")
def meta_post():
    data = request.get_json(force=True, silent=True) or {}
    mezok = data.get("mezok"); listak = data.get("listak")
    if not isinstance(mezok, list) or not isinstance(listak, dict):
        return jsonify({"ok": False, "error": "Adj meg 'mezok' listát és 'listak' szótárt."}), 400
    save_meta(mezok, listak)
    return jsonify({"ok": True})

# ======= ADAT ENDPOINTOK =======
@app.get("/data")
def data_get():
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
    Desktop szinkron / upsert: {"mezok":[...], "listak":{...}, "adatok":[{...}, ...]}
    Nem töröl, csak beszúr/frissít. (Törléshez lásd: /delete)
    """
    payload = request.get_json(force=True, silent=True) or {}
    mezok = payload.get("mezok"); listak = payload.get("listak"); adatok = payload.get("adatok", [])
    if isinstance(mezok, list) and isinstance(listak, dict):
        save_meta(mezok, listak)

    for rec in adatok:
        if not isinstance(rec, dict):
            continue
        az = (rec.get("Azonosító") or "").strip() or gen_id()
        rec["Azonosító"] = az
        row = Adat.query.filter_by(azonosito=az).first()
        if row:
            row.data = json.dumps(rec, ensure_ascii=False)
            row.deleted = 0
        else:
            db.session.add(Adat(azonosito=az, data=json.dumps(rec, ensure_ascii=False), deleted=0))
    db.session.commit()
    return jsonify({"ok": True})

@app.post("/delete")
def delete_bulk():
    """
    Törlés (soft delete): body: {"azonositok": ["ID1","ID2",...]}
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
    # Ha JSON a kérés, JSON-nal válaszolunk
    if request.is_json or request.headers.get("Accept","").startswith("application/json"):
        return jsonify({"ok": True})
    return redirect(url_for("qr_page"))

# ======= EDIT / QR =======
@app.route("/edit/<azonosito>", methods=["GET", "POST"])
def edit_row(azonosito):
    row = Adat.query.filter_by(azonosito=azonosito, deleted=0).first()
    if not row:
        abort(404)
    try:
        rec = json.loads(row.data or "{}")
    except Exception:
        rec = {}

    meta = load_meta()

    if request.method == "POST":
        # Törlés gomb?
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
        # üres rekordot ne tartsunk meg: ha minden üres az Azonosítón kívül -> töröljük
        if is_all_empty_except_id(new_rec):
            row.deleted = 1
        else:
            row.data = json.dumps(new_rec, ensure_ascii=False)
            row.deleted = 0
        db.session.commit()
        return redirect(url_for("edit_row", azonosito=azonosito))

    return render_template("edit.html", rec=rec, mezok=meta["mezok"], listak=meta["listak"], azonosito=azonosito)

@app.route("/qr", methods=["GET", "POST"])
def qr_page():
    meta = load_meta()
    msg = None
    created = None
    if request.method == "POST":
        form = request.form.to_dict()
        az = (form.get("Azonosító") or "").strip().upper() or gen_id()
        # rekord összeállítás
        rec = {}
        for f in meta["mezok"]:
            if f == "Azonosító":
                rec[f] = az
            else:
                rec[f] = form.get(f, "")
        # ha minden üres az Azonosítón kívül → NE hozzunk létre rekordot
        if is_all_empty_except_id(rec):
            msg = "Nem jött létre tétel: nem adtál meg adatot."
            return render_template("qr.html", mezok=meta["mezok"], listak=meta["listak"], created=None, msg=msg)

        # upsert (ha volt már ilyen azonosító és törölt, visszahozzuk)
        row = Adat.query.filter_by(azonosito=az).first()
        if row:
            row.data = json.dumps(rec, ensure_ascii=False)
            row.deleted = 0
        else:
            db.session.add(Adat(azonosito=az, data=json.dumps(rec, ensure_ascii=False), deleted=0))
        db.session.commit()
        created = az
    return render_template("qr.html", mezok=meta["mezok"], listak=meta["listak"], created=created, msg=msg)

@app.route("/qrimg/<azonosito>.png")
def qr_image(azonosito):
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

# ======= MAIN =======
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_schema()
    app.run(host="0.0.0.0", port=5000)
