# qr_app.py (desktop) — mezők/legördülők szerkesztése, szerver szinkron, A4 2x2 PDF, szerveres törlés
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import json
import qrcode
from PIL import Image, ImageTk, ImageDraw, ImageFont
import tempfile
import os
import platform
import tkinter.font as tkfont
import requests
import uuid

# (Ajánlott) TLS cert megbízhatóság Windows alatt
try:
    import certifi
    REQ = {"timeout": 15, "verify": certifi.where()}
except Exception:
    REQ = {"timeout": 15}

# ====== ÁLLÍTSD A SAJÁT DOMAINEDRE ======
SERVER_URL = "https://qr-app-emfo.onrender.com"

# --- Globális adatok ---
adatok = []
fix_mezok = [
    "Azonosító", "Sorszám", "Fémzárszám",
    "Beszállító", "Név", "Fok", "Hely",
    "Súly", "Megjegyzés", "Osztály"
]
mezok = fix_mezok.copy()

# Legördülő opciók (alap; szinkron után a szerver felülírhatja)
listak = {
    "Beszállító": ["Beszállító 1", "Beszállító 2", "Beszállító 3"],
    "Hely": ["Raktár A", "Raktár B", "Kijelölt hely"],
    "Osztály": ["Fénykép", "Eladva", "Javításra"],
}

# --- Hasznos ---
def gen_id(n=8):
    return uuid.uuid4().hex[:n].upper()

# --- API segédfüggvények ---
def api_get_data():
    try:
        r = requests.get(f"{SERVER_URL}/data", **REQ)
        if r.status_code >= 400:
            messagebox.showerror("Szerver hiba", f"GET /data -> {r.status_code}\n{r.text[:400]}")
            return None
        return r.json()
    except requests.exceptions.SSLError as e:
        messagebox.showerror("SSL hiba", f"Tanúsítvány/HTTPS gond: {e}")
        return None
    except Exception as e:
        messagebox.showerror("Hiba", f"GET /data kivétel: {e}")
        return None

def api_update_data(full_data):
    """Teljes push /update-re (mezők + listák + összes adat); a szerver upsert-el Azonosító alapján."""
    try:
        r = requests.post(f"{SERVER_URL}/update", json=full_data, **REQ)
        if r.status_code >= 400:
            messagebox.showerror("Szerver hiba", f"POST /update -> {r.status_code}\n{r.text[:400]}")
            return False
        return True
    except requests.exceptions.SSLError as e:
        messagebox.showerror("SSL hiba", f"Tanúsítvány/HTTPS gond: {e}")
        return False
    except Exception as e:
        messagebox.showerror("Hiba", f"POST /update kivétel: {e}")
        return False

def api_update_row(mezok_list, listak_dict, row_data):
    """EGY rekord upsert /update-re (a szerver így is érti)."""
    try:
        payload = {"mezok": mezok_list, "listak": listak_dict, "adatok": [row_data]}
        r = requests.post(f"{SERVER_URL}/update", json=payload, **REQ)
        if r.status_code >= 400:
            messagebox.showerror("Szerver hiba", f"POST /update (1) -> {r.status_code}\n{r.text[:400]}")
            return False
        return True
    except Exception as e:
        messagebox.showerror("Hiba", f"POST /update kivétel: {e}")
        return False

def api_delete_rows(azonositok):
    """Tételek törlése (soft delete) a szerveren, hogy ne jöjjenek vissza szinkronnál."""
    try:
        r = requests.post(f"{SERVER_URL}/delete", json={"azonositok": azonositok}, **REQ)
        if r.status_code >= 400:
            messagebox.showerror("Szerver hiba", f"POST /delete -> {r.status_code}\n{r.text[:400]}")
            return False
        return True
    except Exception as e:
        messagebox.showerror("Hiba", f"Törlés szerveren nem sikerült:\n{e}")
        return False

# --- Szinkron ---
def sync_from_server():
    global adatok, mezok, listak
    data = api_get_data()
    if not data:
        return
    adatok = data.get("adatok", [])
    mezok = data.get("mezok", fix_mezok.copy())
    listak = data.get("listak", {})
    update_tree()
    messagebox.showinfo("Szinkron", "Szerver → helyi szinkron kész.")

def sync_to_server():
    """Összes jelenlegi rekord + mezők + legördülők felküldése (upsert)."""
    full = {"mezok": mezok, "listak": listak, "adatok": adatok}
    if api_update_data(full):
        messagebox.showinfo("Mentés", "Adatok mentve a szerverre.")

# --- UI: táblázat ---
def update_tree():
    # Azonosító marad használatban, de nem jelenítjük meg oszlopként
    display_columns = [c for c in mezok if c != "Azonosító"]
    tree["columns"] = display_columns
    tree["show"] = "headings"

    for col in display_columns:
        tree.heading(col, text=col)
        tree.column(col, width=150, anchor="center", stretch=tk.NO)

    for i in tree.get_children():
        tree.delete(i)
    for idx, sor in enumerate(adatok):
        values = [sor.get(f, "") for f in display_columns]
        tree.insert("", "end", iid=idx, values=values)

    resize_columns()

def resize_columns():
    factor = scale.get()
    cell_font = tkfont.Font(family="Arial", size=factor)
    heading_font = tkfont.Font(family="Arial", size=factor, weight="bold")

    for col in tree["columns"]:
        heading_width = heading_font.measure(tree.heading(col)["text"]) + 20
        max_cell_width = 0
        for child in tree.get_children():
            val = tree.set(child, col)
            w = cell_font.measure(val) + 20
            if w > max_cell_width:
                max_cell_width = w
        new_width = max(heading_width, max_cell_width, 150)
        tree.column(col, width=new_width)

    tree.update_idletasks()

# --- Mezők kezelése ---
def mezok_kezelese():
    ablak = tk.Toplevel(root); ablak.title("Mezők szerkesztése"); ablak.geometry("400x420")
    lb = tk.Listbox(ablak, selectmode="browse"); lb.pack(fill="both", expand=True, padx=10, pady=10)

    def refresh():
        lb.delete(0, tk.END)
        for m in mezok:
            lb.insert(tk.END, m)

    def uj():
        neve = simpledialog.askstring("Új mező", "Mező neve:", parent=ablak)
        if not neve: return
        if neve in mezok:
            messagebox.showwarning("Figyelem", "Már létezik ilyen mező!")
            return
        mezok.append(neve)
        for r in adatok:
            r.setdefault(neve, "")
        refresh(); update_tree(); sync_to_server()

    def torol():
        sel = lb.curselection()
        if not sel:
            messagebox.showwarning("Figyelem", "Válassz ki egy mezőt!")
            return
        idx = sel[0]; nev = mezok[idx]
        if nev == "Azonosító":
            messagebox.showerror("Hiba", "Az 'Azonosító' mezőt nem törölheted.")
            return
        if not messagebox.askyesno("Törlés", f"Törlöd a(z) '{nev}' mezőt?"):
            return
        mezok.pop(idx)
        for r in adatok:
            r.pop(nev, None)
        listak.pop(nev, None)
        refresh(); update_tree(); sync_to_server()

    def atnevez():
        sel = lb.curselection()
        if not sel:
            messagebox.showwarning("Figyelem", "Válassz ki egy mezőt!")
            return
        idx = sel[0]; old = mezok[idx]
        if old == "Azonosító":
            messagebox.showerror("Hiba", "Az 'Azonosító' mezőt nem lehet átnevezni.")
            return
        new = simpledialog.askstring("Mező átnevezése", "Új név:", initialvalue=old, parent=ablak)
        if not new: return
        if new in mezok:
            messagebox.showwarning("Figyelem", "Már létezik ilyen mező!")
            return
        mezok[idx] = new
        for r in adatok:
            if old in r:
                r[new] = r.pop(old)
            else:
                r.setdefault(new, "")
        if old in listak:
            listak[new] = listak.pop(old)
        refresh(); update_tree(); sync_to_server()

    def fel():
        sel = lb.curselection(); 
        if not sel: return
        idx = sel[0]
        if idx == 0: return
        mezok[idx-1], mezok[idx] = mezok[idx], mezok[idx-1]
        refresh(); lb.select_set(idx-1); update_tree(); sync_to_server()

    def le():
        sel = lb.curselection(); 
        if not sel: return
        idx = sel[0]
        if idx >= len(mezok)-1: return
        mezok[idx+1], mezok[idx] = mezok[idx], mezok[idx+1]
        refresh(); lb.select_set(idx+1); update_tree(); sync_to_server()

    btn = tk.Frame(ablak); btn.pack(pady=5)
    tk.Button(btn, text="Új mező", command=uj).grid(row=0, column=0, padx=4, pady=2)
    tk.Button(btn, text="Törlés", command=torol).grid(row=0, column=1, padx=4, pady=2)
    tk.Button(btn, text="Átnevez", command=atnevez).grid(row=0, column=2, padx=4, pady=2)
    tk.Button(btn, text="Fel", command=fel).grid(row=1, column=0, padx=4, pady=2)
    tk.Button(btn, text="Le", command=le).grid(row=1, column=1, padx=4, pady=2)
    tk.Button(ablak, text="Bezárás", command=ablak.destroy).pack(pady=6)

    ablak.transient(root); ablak.grab_set(); refresh()

# --- Sor felvitel / módosítás ---
def sor_beviteli_ablak(modositott_sor=None, idx=None):
    ablak = tk.Toplevel(root); ablak.title("Sor hozzáadása / módosítása")
    entries = {}

    for i, field in enumerate(mezok):
        tk.Label(ablak, text=field).grid(row=i, column=0, padx=5, pady=5, sticky="w")
        if field == "Azonosító":
            e = tk.Entry(ablak, width=50)
            if modositott_sor:
                e.insert(0, modositott_sor.get(field, ""))
                e.config(state="disabled")
            else:
                e.insert(0, "Automatikusan generálva"); e.config(state="disabled")
        elif field in listak:
            e = ttk.Combobox(ablak, values=listak[field], width=48)
        else:
            e = tk.Entry(ablak, width=50)
        e.grid(row=i, column=1, padx=5, pady=5)
        if modositott_sor and field != "Azonosító":
            val = modositott_sor.get(field, "")
            if isinstance(e, ttk.Combobox):
                e.set(val)
            else:
                e.insert(0, val)
        entries[field] = e

    def ment():
        sor = {f: entries[f].get() for f in entries if f != "Azonosító"}

        # Automatikus Sorszám Név+Fok+Beszállító szerint
        nev = sor.get("Név", "").strip()
        fok = sor.get("Fok", "").strip()
        besz = sor.get("Beszállító", "").strip()
        if nev and fok and besz:
            existing = [d for d in adatok if d.get("Név","").strip()==nev and d.get("Fok","").strip()==fok and d.get("Beszállító","").strip()==besz]
            sor["Sorszám"] = len(existing) + 1
        else:
            sor["Sorszám"] = 1

        if modositott_sor and idx is not None:
            sor["Azonosító"] = modositott_sor["Azonosító"]
            adatok[idx] = sor
            if not api_update_row(mezok, listak, sor): return
        else:
            az = str(uuid.uuid4())
            if any(d.get("Azonosító")==az for d in adatok):
                messagebox.showerror("Hiba", "Az azonosító ütközik, próbáld újra.")
                return
            sor["Azonosító"] = az
            adatok.append(sor)
            if not api_update_row(mezok, listak, sor): return

        update_tree()
        ablak.destroy()

    tk.Button(ablak, text="Mentés", command=ment).grid(row=len(mezok), column=0, columnspan=2, pady=10)

# --- Törlés (szerverrel együtt) ---
def torles():
    selected = tree.selection()
    if not selected:
        messagebox.showwarning("Figyelem", "Válassz ki egy sort a törléshez!")
        return
    if not messagebox.askyesno("Törlés", "Biztosan törlöd a kiválasztott sort/sorokat?"):
        return

    ids = []
    for i in selected:
        idx = int(i)
        if 0 <= idx < len(adatok):
            az = adatok[idx].get("Azonosító")
            if az: ids.append(az)

    if not api_delete_rows(ids):
        return

    # helyileg is kivesszük
    for i in sorted([int(x) for x in selected], reverse=True):
        if 0 <= i < len(adatok):
            del adatok[i]

    update_tree()
    # friss állapot visszahúzása biztos ami biztos
    sync_from_server()

# --- Legördülők szerkesztése ---
def szerkesztes_legordulok():
    ablak = tk.Toplevel(root); ablak.title("Legördülők szerkesztése")

    tk.Label(ablak, text="Mező kiválasztása:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
    field_cb = ttk.Combobox(ablak, values=sorted(listak.keys()), width=30); field_cb.grid(row=0, column=1, padx=5, pady=5)

    tk.Label(ablak, text="Opció kiválasztása:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
    opt_cb = ttk.Combobox(ablak, width=30); opt_cb.grid(row=1, column=1, padx=5, pady=5)

    def update_options(event=None):
        f = field_cb.get(); opt_cb.set("")
        opt_cb["values"] = sorted(listak.get(f, [])) if f in listak else []

    field_cb.bind("<<ComboboxSelected>>", update_options)

    def uj_opcio():
        f = field_cb.get()
        if not f:
            messagebox.showwarning("Figyelmeztetés", "Előbb válassz mezőt!")
            return
        val = simpledialog.askstring("Új opció", "Új érték:", parent=ablak)
        if not val: return
        listak.setdefault(f, [])
        if val not in listak[f]:
            listak[f].append(val)
            update_options(); opt_cb["values"] = sorted(listak[f])
            sync_to_server(); messagebox.showinfo("Siker", f"Új opció: {val}")

    def mod_opcio():
        f = field_cb.get(); old = opt_cb.get()
        if not f or not old:
            messagebox.showwarning("Figyelmeztetés", "Válassz mezőt és opciót!")
            return
        new = simpledialog.askstring("Opció módosítás", "Új érték:", initialvalue=old, parent=ablak)
        if not new or new == old: return
        i = listak[f].index(old); listak[f][i] = new
        update_options(); opt_cb["values"] = sorted(listak[f]); opt_cb.set(new)
        sync_to_server(); messagebox.showinfo("Siker", f"Módosítva: {old} → {new}")

    def torol_opcio():
        f = field_cb.get(); sel = opt_cb.get()
        if not f or not sel:
            messagebox.showwarning("Figyelmeztetés", "Válassz mezőt és opciót!")
            return
        listak[f].remove(sel); update_options(); opt_cb["values"] = sorted(listak[f]); opt_cb.set("")
        sync_to_server(); messagebox.showinfo("Siker", f"Törölve: {sel}")

    tk.Button(ablak, text="Új opció", command=uj_opcio).grid(row=2, column=1, padx=5, pady=5, sticky="e")
    tk.Button(ablak, text="Opció módosítás", command=mod_opcio).grid(row=3, column=1, padx=5, pady=5, sticky="e")
    tk.Button(ablak, text="Opció törlés", command=torol_opcio).grid(row=4, column=1, padx=5, pady=5, sticky="e")

    def close():
        sync_to_server(); update_tree(); ablak.destroy()
    tk.Button(ablak, text="Mentés és bezárás", command=close).grid(row=5, column=0, columnspan=2, pady=10)

    ablak.transient(root); ablak.grab_set()

# --- QR előnézet + nyomtatás (darabonként) ---
def qr_generalas():
    selected = tree.selection()
    if not selected:
        messagebox.showwarning("Figyelem", "Válassz legalább egy sort!")
        return

    popup = tk.Toplevel(root); popup.title("QR Kódok"); popup.geometry("800x600")
    canvas = tk.Canvas(popup); vs = ttk.Scrollbar(popup, orient="vertical", command=canvas.yview)
    frame = tk.Frame(canvas)
    frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0,0), window=frame, anchor="nw"); canvas.configure(yscrollcommand=vs.set)
    canvas.pack(side="left", fill="both", expand=True); vs.pack(side="right", fill="y")

    qr_images = []

    for i in selected:
        sor = adatok[int(i)]
        url = f"{SERVER_URL}/edit/{sor['Azonosító']}"
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(url); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qr_images.append(img)
        disp = img.resize((260, 260), getattr(Image, "LANCZOS", Image.BICUBIC))
        tkimg = ImageTk.PhotoImage(disp)

        item = tk.Frame(frame, borderwidth=2, relief="solid", pady=10)
        tk.Label(item, text=f"Azonosító: {sor['Azonosító']}").pack(pady=5)
        lab = tk.Label(item, image=tkimg); lab.image = tkimg; lab.pack(pady=(0,10))
        item.pack(fill="x", expand=True, padx=10)

    def nyomtat():
        for img in qr_images:
            try:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                img.save(tmp.name); tmp.close()
                if platform.system() == "Windows":
                    os.startfile(tmp.name, "print")
                else:
                    os.system(f"lpr {tmp.name}")
            except Exception as e:
                messagebox.showerror("Nyomtatási hiba", str(e))

    tk.Button(popup, text="Nyomtatás", command=nyomtat).pack(pady=10, side="bottom")

# --- Lokális mentés/betöltés ---
def ment_local():
    path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
    if not path: return
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"mezok": mezok, "adatok": adatok, "listak": listak}, f, ensure_ascii=False, indent=2)
    messagebox.showinfo("Mentve", f"Elmentve: {path}")

def betolt_local():
    path = filedialog.askopenfilename(filetypes=[("JSON","*.json")])
    if not path: return
    global adatok, mezok, listak
    with open(path, "r", encoding="utf-8") as f:
        blob = json.load(f)
        if isinstance(blob, list):
            adatok = blob
            if adatok:
                keys = set()
                for r in adatok: keys.update(r.keys())
                ordered = fix_mezok.copy()
                for k in keys:
                    if k not in ordered: ordered.append(k)
                mezok = ordered
            else:
                mezok = fix_mezok.copy()
            listak = {}
        else:
            adatok = blob.get("adatok", [])
            mezok = blob.get("mezok", fix_mezok.copy())
            listak = blob.get("listak", {})
            listak.setdefault("Beszállító", ["Beszállító 1","Beszállító 2","Beszállító 3"])
            listak.setdefault("Hely", ["Raktár A","Raktár B","Kijelölt hely"])
            listak.setdefault("Osztály", ["Fénykép","Eladva","Javításra"])
    sync_to_server(); update_tree(); messagebox.showinfo("Betöltve", path)

# --- A4 2×2 PDF 100% nyomtatás (több kiválasztott) ---
def pdf_100_nyomtat():
    """Több kiválasztott rekord → A4 2x2 PDF oldalak, 100% (SumatraPDF 'noscale' ha elérhető)."""
    try:
        DPI = 300
        pages, A4_W, A4_H = build_pages_fullA4_from_selection(DPI=DPI)
        if not pages: return
        import subprocess, sys
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        path = tmp.name; tmp.close()
        first, rest = pages[0], pages[1:]
        first.save(path, save_all=True, append_images=rest, resolution=DPI)

        # Próbáljuk SumatraPDF-et (noscale)
        candidates = [
            r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
            r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
            os.path.join(os.path.dirname(sys.executable), "SumatraPDF.exe"),
            os.path.join(os.getcwd(), "SumatraPDF.exe"),
        ]
        exe = next((c for c in candidates if os.path.exists(c)), None)
        if exe:
            cmd = f'"{exe}" -print-to-default -print-settings "noscale" -silent "{path}"'
            try:
                subprocess.run(cmd, shell=True, check=True)
                messagebox.showinfo("Nyomtatás", "Elküldve a nyomtatóra (100%, noscale).")
                return
            except Exception:
                pass
        # Fallback: csak megnyitjuk; ott állítsd 100%-ra
        try:
            os.startfile(path)
            messagebox.showinfo("PDF", "Megnyílt a PDF. Nyomtatásnál válaszd a 'Tényleges méret / 100%' opciót.")
        except Exception:
            messagebox.showwarning("Figyelem", f"PDF elkészült: {path}")
    except Exception as e:
        import traceback; traceback.print_exc()
        messagebox.showerror("Hiba", f"PDF hiba: {e}")

def build_pages_fullA4_from_selection(DPI=300):
    """A4 (210x297mm) 2x2 teljes felosztás, margó nélkül."""
    selected = tree.selection()
    if not selected:
        messagebox.showwarning("Figyelem", "Válassz ki legalább egy sort!")
        return [], 0, 0

    def mm_to_px(mm): return int(round(mm / 25.4 * DPI))
    A4_W, A4_H = mm_to_px(210), mm_to_px(297)
    SLOT_W, SLOT_H = A4_W // 2, A4_H // 2
    INSET = 0

    items = []
    for i in selected:
        sor = adatok[int(i)]
        az = sor.get("Azonosító", "")
        url = f"{SERVER_URL}/edit/{az}"
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(url); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        items.append(img)

    # Töltsük ki a 4-es oldalakat
    from PIL import Image as PILImage
    while len(items) % 4 != 0:
        items.append(PILImage.new("RGB", (300, 300), "white"))

    pages = []
    for start in range(0, len(items), 4):
        page = PILImage.new("RGB", (A4_W, A4_H), "white")
        positions = [
            (0 * SLOT_W, 0 * SLOT_H),
            (1 * SLOT_W, 0 * SLOT_H),
            (0 * SLOT_W, 1 * SLOT_H),
            (1 * SLOT_W, 1 * SLOT_H),
        ]
        for img, (x, y) in zip(items[start:start+4], positions):
            target_w = SLOT_W - 2 * INSET
            target_h = SLOT_H - 2 * INSET
            side = min(target_w, target_h)
            resample = getattr(PILImage, 'LANCZOS', Image.BICUBIC)
            qr_resized = img.resize((side, side), resample)
            paste_x = x + (SLOT_W - side) // 2
            paste_y = y + (SLOT_H - side) // 2
            page.paste(qr_resized, (paste_x, paste_y))
        pages.append(page)
    return pages, A4_W, A4_H

# --- Fő UI ---
root = tk.Tk()
root.title("QR Kód Generáló – Szerver szinkron")

style = ttk.Style(); style.theme_use("default")
style.configure("Custom.Treeview", background="white", foreground="black",
                rowheight=25, fieldbackground="white", bordercolor="black",
                borderwidth=1, relief="solid", font=("Arial", 10))
style.map("Custom.Treeview", background=[("selected", "#004080")], foreground=[("selected", "white")])
style.configure("Custom.Treeview.Heading", font=("Arial", 10, "bold"), bordercolor="black", borderwidth=1, relief="solid")

frame_main = tk.Frame(root); frame_main.pack(fill="both", expand=True)
tree = ttk.Treeview(frame_main, show="headings", selectmode="extended", style="Custom.Treeview")
vsb = ttk.Scrollbar(frame_main, orient="vertical", command=tree.yview)
hsb = ttk.Scrollbar(frame_main, orient="horizontal", command=tree.xview)
tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
vsb.pack(side="right", fill="y"); hsb.pack(side="bottom", fill="x")
tree.pack(fill="both", expand=True, padx=10, pady=10)

frame = tk.Frame(root); frame.pack(pady=8)
frame_4up = tk.Frame(root); frame_4up.pack(pady=4)

tk.Button(frame, text="Új sor", command=lambda: sor_beviteli_ablak()).grid(row=0, column=0, padx=5)
tk.Button(frame, text="Módosítás", command=lambda: sor_beviteli_ablak(adatok[int(tree.selection()[0])], int(tree.selection()[0])) if tree.selection() else messagebox.showwarning("Figyelem","Válassz sort!")).grid(row=0, column=1, padx=5)
tk.Button(frame, text="Törlés", command=torles).grid(row=0, column=2, padx=5)
tk.Button(frame, text="QR előnézet", command=qr_generalas).grid(row=0, column=3, padx=5)
tk.Button(frame, text="Legördülők szerkesztése", command=szerkesztes_legordulok).grid(row=0, column=4, padx=5)
tk.Button(frame, text="Mezők szerkesztése", command=mezok_kezelese).grid(row=0, column=5, padx=5)
tk.Button(frame, text="Szinkron (Szerver→Helyi)", command=sync_from_server).grid(row=0, column=6, padx=5)
tk.Button(frame, text="Mentés Szerverre", command=sync_to_server).grid(row=0, column=7, padx=5)
tk.Button(frame, text="Lokális mentés", command=ment_local).grid(row=0, column=8, padx=5)
tk.Button(frame, text="Lokális betöltés", command=betolt_local).grid(row=0, column=9, padx=5)

tk.Button(frame_4up, text="A4 4× QR – PDF (100%)", command=pdf_100_nyomtat).pack()

zoom_frame = tk.Frame(root); zoom_frame.pack(side="bottom", fill="x", padx=5, pady=5)
scale = tk.Scale(zoom_frame, from_=8, to=24, orient="horizontal", command=lambda v: (style.configure("Custom.Treeview", rowheight=int(int(v)*1.5)+10, font=("Arial", int(v))), style.configure("Custom.Treeview.Heading", font=("Arial", int(v), "bold")), resize_columns()), label="Zoom")
scale.set(10); scale.pack(side="right")

# Indulás: szinkron, ha elérhető a szerver
try:
    sync_from_server()
except Exception:
    update_tree()

root.mainloop()
