# migrate_add_azonosito.py
import json, uuid
from sqlalchemy import text
from server import app, db, Adat  # a Te appod moduljai

def gen_id():
    return uuid.uuid4().hex[:8].upper()

with app.app_context():
    # 1) Oszlop hozzáadása, ha hiányzik
    cols = [r[1] for r in db.session.execute(text("PRAGMA table_info(adat)")).fetchall()]
    if 'azonosito' not in cols:
        db.session.execute(text("ALTER TABLE adat ADD COLUMN azonosito TEXT"))
        db.session.commit()

    # 2) Adatok feltöltése
    seen = set()
    rows = Adat.query.all()
    for row in rows:
        az = getattr(row, 'azonosito', None)
        if not az or not str(az).strip():
            try:
                rec = json.loads(row.data or "{}")
                base = (rec.get("Azonosító") or "").strip().upper()
            except Exception:
                base = ""
            if not base:
                base = gen_id()
            cand = base
            n = 1
            # ütközések elkerülése
            while cand in seen or db.session.execute(text("SELECT 1 FROM adat WHERE azonosito=:a"), {"a": cand}).fetchone():
                n += 1
                cand = f"{base}-{n}"
            row.azonosito = cand
            seen.add(cand)
    db.session.commit()

    # 3) Egyedi index
    db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_adat_azonosito ON adat(azonosito)"))
    db.session.commit()

print("Kész: az 'adat.azonosito' oszlop létrejött és feltöltöttem.")
