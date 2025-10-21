# qr_app.py (frissített: mezők szerkesztése, hozzáadása, törlése, sorrend változtatása)
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

# Szerver URL (frissítsd a Render URL-re telepítés után, pl. https://your-app.onrender.com)
SERVER_URL = "https://qr-app-emfo.onrender.com"  # Helyi teszteléshez; frissítsd a Render URL-re!

# --- Globális változók és adatok ---
adatok = []
fix_mezok = ["Azonosító", "Sorszám", "Fémzárszám", "Beszállító", "Név", "Fok", "Hely", "Súly", "Megjegyzés", "Osztály"]
mezok = fix_mezok.copy()

# Legördülő lista opciók
beszallito_opciok = ["Beszállító 1", "Beszállító 2", "Beszállító 3"]
hely_opciok = ["Raktár A", "Raktár B", "Kijelölt hely"]
osztaly_opciok = ["Fénykép", "Eladva", "Javításra"]

listak = {
    "Beszállító": beszallito_opciok,
    "Hely": hely_opciok,
    "Osztály": osztaly_opciok
}

# --- API segédfunkciók ---
def api_get_data():
    try:
        response = requests.get(f"{SERVER_URL}/data", timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        messagebox.showerror("Hiba", f"Szerver hiba: {e}")
        return None

def api_update_data(full_data):
    """Teljes push /update-re (mezők + listák + összes adat) – a szerver upsert-el Azonosító alapján."""
    try:
        response = requests.post(f"{SERVER_URL}/update", json=full_data, timeout=20)
        response.raise_for_status()
        return True
    except Exception as e:
        messagebox.showerror("Hiba", f"Szerver hiba: {e}")
        return False

def api_update_row(mezok_list, listak_dict, row_data):
    """
    EGY rekord upsert /update-re, nem /edit PUT-ra.
    Így a szerver biztosan érti (ugyanaz, mint a teljes push, csak 1 adatlappal).
    """
    try:
        payload = {
            "mezok": mezok_list,
            "listak": listak_dict,
            "adatok": [row_data],
        }
        response = requests.post(f"{SERVER_URL}/update", json=payload, timeout=15)
        response.raise_for_status()
        return True
    except Exception as e:
        messagebox.showerror("Hiba", f"Szerver hiba: {e}")
        return False

# --- Szinkronizálás szerverrel ---
def sync_from_server():
    global adatok, mezok, listak
    data = api_get_data()
    if data:
        adatok = data.get("adatok", [])
        mezok = data.get("mezok", fix_mezok.copy())
        listak = data.get("listak", {})
        update_tree()
        messagebox.showinfo("Szinkronizálva", "Adatok szinkronizálva a szerverrel.")

def sync_to_server():
    full_data = {"mezok": mezok, "adatok": adatok, "listak": listak}
    if api_update_data(full_data):
        messagebox.showinfo("Mentve", "Adatok mentve a szerverre.")

# --- Treeview frissítése (főablak) ---
def update_tree():
    # "Azonosító" működjön, de ne legyen látható a táblában
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

# --- Oszlopok átméretezése ---
def resize_columns():
    factor = scale.get()
    cell_font = tkfont.Font(family="Arial", size=factor)
    heading_font = tkfont.Font(family="Arial", size=factor, weight="bold")

    for col in tree["columns"]:
        heading_width = heading_font.measure(tree.heading(col)["text"]) + 20
        max_cell_width = 0
        for child in tree.get_children():
            cell_value = tree.set(child, col)
            cell_width = cell_font.measure(cell_value) + 20
            if cell_width > max_cell_width:
                max_cell_width = cell_width
        new_width = max(heading_width, max_cell_width, 150)
        tree.column(col, width=new_width)

    tree.update_idletasks()

# --- Mezők kezelése (hozzáadás / törlés / átnevezés / sorrend) ---
def mezok_kezelese():
    ablak = tk.Toplevel(root)
    ablak.title("Mezők szerkesztése")
    ablak.geometry("400x400")

    lb = tk.Listbox(ablak, selectmode="browse")
    lb.pack(fill="both", expand=True, padx=10, pady=10)
    def refresh_listbox():
        lb.delete(0, tk.END)
        for m in mezok:
            lb.insert(tk.END, m)
    refresh_listbox()

    def uj_mezo():
        neve = simpledialog.askstring("Új mező", "Mező neve:", parent=ablak)
        if neve:
            if neve in mezok:
                messagebox.showwarning("Figyelem", "Már létezik ilyen mező!")
                return
            mezok.append(neve)
            # frissítsük minden adatsorban az új kulcsot (üres értékkel)
            for r in adatok:
                r.setdefault(neve, "")
            refresh_listbox()
            update_tree()
            sync_to_server()

    def torol_mezo():
        sel = lb.curselection()
        if not sel:
            messagebox.showwarning("Figyelem", "Válassz ki egy mezőt a törléshez!")
            return
        idx = sel[0]
        nev = mezok[idx]
        if nev == "Azonosító":
            messagebox.showerror("Hiba", "Az 'Azonosító' mezőt nem lehet törölni!")
            return
        if messagebox.askyesno("Törlés", f"Törlöd a(z) '{nev}' mezőt? Ez eltávolítja a mező értékét minden sorból."):
            # eltávolítjuk a mezőt a mezok-ból és az adatokból, valamint a listákból
            mezok.pop(idx)
            for r in adatok:
                if nev in r:
                    del r[nev]
            if nev in listak:
                del listak[nev]
            refresh_listbox()
            update_tree()
            sync_to_server()

    def rename_mezo():
        sel = lb.curselection()
        if not sel:
            messagebox.showwarning("Figyelem", "Válassz ki egy mezőt az átnevezéshez!")
            return
        idx = sel[0]
        old = mezok[idx]
        if old == "Azonosító":
            messagebox.showerror("Hiba", "Az 'Azonosító' mezőt nem lehet átnevezni!")
            return
        new = simpledialog.askstring("Mező átnevezése", "Új név:", initialvalue=old, parent=ablak)
        if new:
            if new in mezok:
                messagebox.showwarning("Figyelem", "Már létezik ilyen mező!")
                return
            # átnevezzük a mezokot
            mezok[idx] = new
            # az adatokban átnevezzük a kulcsokat
            for r in adatok:
                if old in r:
                    r[new] = r.pop(old)
                else:
                    r.setdefault(new, "")
            # ha volt listak bejegyzés az régi név alatt, áthelyezzük
            if old in listak:
                listak[new] = listak.pop(old)
            refresh_listbox()
            update_tree()
            sync_to_server()

    def move_up():
        sel = lb.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx == 0:
            return
        mezok[idx-1], mezok[idx] = mezok[idx], mezok[idx-1]
        refresh_listbox()
        lb.select_set(idx-1)
        update_tree()
        sync_to_server()

    def move_down():
        sel = lb.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx == len(mezok)-1:
            return
        mezok[idx+1], mezok[idx] = mezok[idx], mezok[idx+1]
        refresh_listbox()
        lb.select_set(idx+1)
        update_tree()
        sync_to_server()

    btn_frame = tk.Frame(ablak)
    btn_frame.pack(pady=5)
    tk.Button(btn_frame, text="Új mező", command=uj_mezo).grid(row=0, column=0, padx=4, pady=2)
    tk.Button(btn_frame, text="Törlés", command=torol_mezo).grid(row=0, column=1, padx=4, pady=2)
    tk.Button(btn_frame, text="Átnevez", command=rename_mezo).grid(row=0, column=2, padx=4, pady=2)
    tk.Button(btn_frame, text="Fel", command=move_up).grid(row=1, column=0, padx=4, pady=2)
    tk.Button(btn_frame, text="Le", command=move_down).grid(row=1, column=1, padx=4, pady=2)

    def close():
        sync_to_server()
        update_tree()
        ablak.destroy()

    tk.Button(ablak, text="Mentés és bezárás", command=close).pack(pady=6)

    ablak.transient(root)
    ablak.grab_set()

# --- Sor hozzáadás / módosítás ---
def sor_beviteli_ablak(modositott_sor=None, idx=None):
    ablak = tk.Toplevel(root)
    ablak.title("Sor hozzáadása / módosítása")
    entries = {}

    for i, field in enumerate(mezok):
        tk.Label(ablak, text=field).grid(row=i, column=0, padx=5, pady=5, sticky="w")
        if field == "Azonosító":
            entry = tk.Entry(ablak, width=50)
            if modositott_sor:
                entry.insert(0, modositott_sor.get(field, ""))
                entry.config(state="disabled")  # Nem módosítható
            else:
                entry.insert(0, "Automatikusan generálva")
                entry.config(state="disabled")
        elif field in listak:
            entry = ttk.Combobox(ablak, values=listak[field], width=48)
        else:
            entry = tk.Entry(ablak, width=50)

        entry.grid(row=i, column=1, padx=5, pady=5)

        if modositott_sor and field != "Azonosító":
            ertek = modositott_sor.get(field, "")
            if isinstance(entry, ttk.Combobox):
                entry.set(ertek)
            else:
                entry.insert(0, ertek)
        entries[field] = entry

    def ment():
        sor = {field: entries[field].get() for field in entries if field != "Azonosító"}

        # --- Automatikus sorszámozás Név + Fok + Beszállító szerint ---
        nev = sor.get("Név", "").strip()
        fok = sor.get("Fok", "").strip()
        beszallito = sor.get("Beszállító", "").strip()

        if nev and fok and beszallito:
            # megszámoljuk az eddigi hasonló sorokat
            existing = [
                d for d in adatok
                if d.get("Név", "").strip() == nev
                and d.get("Fok", "").strip() == fok
                and d.get("Beszállító", "").strip() == beszallito
            ]
            sor["Sorszám"] = len(existing) + 1
        else:
            sor["Sorszám"] = 1  # ha hiányzik valami, akkor 1

        if modositott_sor and idx is not None:
            sor["Azonosító"] = modositott_sor["Azonosító"]
            adatok[idx] = sor
            # egy rekord upsert /update-re
            if not api_update_row(mezok, listak, sor):
                return
        else:
            # új rekord — generáljunk egyedi azonosítót
            azonosito = str(uuid.uuid4())
            sor["Azonosító"] = azonosito
            if any(d.get("Azonosító") == azonosito for d in adatok):
                messagebox.showerror("Hiba", "Az azonosító már létezik!")
                return
            adatok.append(sor)
            # és szinkron a szerverre
            if not api_update_row(mezok, listak, sor):
                return

        update_tree()
        ablak.destroy()

    tk.Button(ablak, text="Mentés", command=ment).grid(row=len(mezok), column=0, columnspan=2, pady=10)

# --- Sor törlés (helyi) ---
def torles():
    selected = tree.selection()
    if not selected:
        messagebox.showwarning("Figyelem", "Válassz ki egy sort a törléshez!")
        return
    if messagebox.askyesno("Törlés", "Biztosan törlöd a kiválasztott sort? (Szerverről nem törli automatikusan!)"):
        for i in reversed(selected):
            del adatok[int(i)]
        sync_to_server()
        update_tree()

# --- Sor módosítás ---
def modositas():
    selected = tree.selection()
    if not selected:
        messagebox.showwarning("Figyelem", "Válassz ki egy sort a módosításhoz!")
        return
    idx = int(selected[0])
    sor_beviteli_ablak(adatok[idx], idx)

# --- Legördülők szerkesztése ---
def szerkesztes_legordulok():
    ablak = tk.Toplevel(root)
    ablak.title("Legördülők szerkesztése")

    # Mező kiválasztása
    tk.Label(ablak, text="Mező kiválasztása:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
    field_combobox = ttk.Combobox(ablak, values=sorted(listak.keys()), width=30)
    field_combobox.grid(row=0, column=1, padx=5, pady=5)

    # Opció kiválasztása
    tk.Label(ablak, text="Opció kiválasztása:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
    option_combobox = ttk.Combobox(ablak, width=30)
    option_combobox.grid(row=1, column=1, padx=5, pady=5)

    # Frissíti az opciókat a kiválasztott mező alapján
    def update_options(event=None):
        selected_field = field_combobox.get()
        option_combobox.set("")  # Ürítjük a comboboxot
        if selected_field in listak:
            option_combobox["values"] = sorted(listak[selected_field])
        else:
            option_combobox["values"] = []

    field_combobox.bind("<<ComboboxSelected>>", update_options)

    # Gombok függvényei
    def uj_opcio():
        selected_field = field_combobox.get()
        if not selected_field:
            messagebox.showwarning("Figyelmeztetés", "Előbb válassz ki egy mezőt!")
            return
        new_option = simpledialog.askstring("Új opció", "Új opció értéke:", parent=ablak)
        if new_option and new_option not in listak.get(selected_field, []):
            if selected_field not in listak:
                listak[selected_field] = []
            listak[selected_field].append(new_option)
            update_options(None)  # Frissítjük az opciókat
            option_combobox["values"] = sorted(listak[selected_field])
            sync_to_server()
            messagebox.showinfo("Siker", f"Új opció hozzáadva: {new_option}")

    def modositas_opcio():
        selected_field = field_combobox.get()
        selected_option = option_combobox.get()
        if not selected_field or not selected_option:
            messagebox.showwarning("Figyelmeztetés", "Előbb válassz ki egy mezőt és egy opciót!")
            return
        new_option = simpledialog.askstring("Opció módosítás", "Új érték:", initialvalue=selected_option, parent=ablak)
        if new_option and new_option != selected_option:
            idx = listak[selected_field].index(selected_option)
            listak[selected_field][idx] = new_option
            update_options(None)  # Frissítjük az opciókat
            option_combobox["values"] = sorted(listak[selected_field])
            option_combobox.set(new_option)
            sync_to_server()
            messagebox.showinfo("Siker", f"Opció módosítva: {selected_option} -> {new_option}")

    def torles_opcio():
        selected_field = field_combobox.get()
        selected_option = option_combobox.get()
        if not selected_field or not selected_option:
            messagebox.showwarning("Figyelmeztetés", "Előbb válassz ki egy mezőt és egy opciót!")
            return
        if selected_field in listak and selected_option in listak[selected_field]:
            listak[selected_field].remove(selected_option)
            update_options(None)  # Frissítjük az opciókat
            option_combobox["values"] = sorted(listak[selected_field])
            option_combobox.set("")
            sync_to_server()
            messagebox.showinfo("Siker", f"Opció törölve: {selected_option}")

    # Gombok hozzáadása
    tk.Button(ablak, text="Új opció", command=uj_opcio).grid(row=2, column=1, padx=5, pady=5)
    tk.Button(ablak, text="Opció módosítás", command=modositas_opcio).grid(row=3, column=1, padx=5, pady=5)
    tk.Button(ablak, text="Opció törlés", command=torles_opcio).grid(row=4, column=1, padx=5, pady=5)

    # Bezáráskor szinkronizáció
    def close():
        sync_to_server()
        update_tree()
        ablak.destroy()

    tk.Button(ablak, text="Mentés és bezárás", command=close).grid(row=5, column=0, columnspan=2, pady=10)

    ablak.transient(root)  # Megakadályozza, hogy az ablak a háttérbe kerüljön
    ablak.grab_set()  # Fókuszban tartja az ablakot

# --- QR generálás ---
def qr_generalas():
    selected = tree.selection()
    if not selected:
        messagebox.showwarning("Figyelem", "Válassz ki legalább egy sort a QR generáláshoz!")
        return

    qr_popup = tk.Toplevel(root)
    qr_popup.title("QR Kódok")
    qr_popup.geometry("800x600")

    canvas = tk.Canvas(qr_popup)
    scrollbar = ttk.Scrollbar(qr_popup, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas)

    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )

    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    qr_images = []

    for i in selected:
        sor = adatok[int(i)]
        qr_data = f"{SERVER_URL}/edit/{sor['Azonosító']}"
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qr_images.append(img)

        # a megjelenítéshez készítünk kicsinyített fotót
        disp = img.resize((260, 260), getattr(Image, "LANCZOS", Image.BICUBIC))
        img_tk = ImageTk.PhotoImage(disp)

        qr_item_frame = tk.Frame(scrollable_frame, borderwidth=2, relief="solid", pady=10)
        label = tk.Label(qr_item_frame, text=f"Azonosító: {sor['Azonosító']}")
        label.pack(pady=5)

        qr_label = tk.Label(qr_item_frame, image=img_tk)
        qr_label.image = img_tk
        qr_label.pack(pady=(0, 10))

        qr_item_frame.pack(fill="x", expand=True, padx=10)

    update_tree()

    def nyomtat():
        for img in qr_images:
            try:
                tmpfile = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                img.save(tmpfile.name)
                tmpfile.close()
                if platform.system() == "Windows":
                    os.startfile(tmpfile.name, "print")
                else:
                    os.system(f"lpr {tmpfile.name}")
            except Exception as e:
                messagebox.showerror("Nyomtatási hiba", f"Hiba történt a nyomtatás során: {e}")

    print_button = tk.Button(qr_popup, text="Nyomtatás", command=nyomtat)
    print_button.pack(pady=10, side="bottom")

# --- Mentés JSON ---
def ment_local():
    path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files","*.json")])
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"mezok": mezok, "adatok": adatok, "listak": listak}, f, ensure_ascii=False, indent=2)
        messagebox.showinfo("Mentve", f"Adatok elmentve lokálisan: {path}")

# --- Betöltés JSON ---
def betolt_local():
    path = filedialog.askopenfilename(filetypes=[("JSON files","*.json")])
    if path:
        global adatok, mezok, listak
        with open(path, "r", encoding="utf-8") as f:
            data_to_load = json.load(f)
            if isinstance(data_to_load, list):
                adatok = data_to_load
                if adatok:
                    all_keys = set()
                    for row in adatok:
                        all_keys.update(row.keys())
                    ordered_keys = fix_mezok.copy()
                    for key in all_keys:
                        if key not in ordered_keys:
                            ordered_keys.append(key)
                    mezok = ordered_keys
                else:
                    mezok = fix_mezok.copy()
                listak = {}
            else:
                adatok = data_to_load.get("adatok", [])
                mezok = data_to_load.get("mezok", fix_mezok.copy())
                listak = data_to_load.get("listak", {})

                if "Beszállító" not in listak:
                    listak["Beszállító"] = ["Beszállító 1", "Beszállító 2", "Beszállító 3"]
                if "Hely" not in listak:
                    listak["Hely"] = ["Raktár A", "Raktár B", "Kijelölt hely"]
                if "Osztály" not in listak:
                    listak["Osztály"] = ["Fénykép", "Eladva", "Javításra"]

        sync_to_server()
        update_tree()
        messagebox.showinfo("Betöltve", f"Adatok betöltve lokálisan: {path}")

# --- Zoom ---
def zoom(val):
    factor = int(val)
    style.configure("Custom.Treeview", rowheight=int(factor * 1.5) + 10, font=("Arial", factor))
    style.configure("Custom.Treeview.Heading", font=("Arial", factor, "bold"))
    resize_columns()

# --- Főablak ---
root = tk.Tk()
root.title("QR Kód Generáló - Dinamikus Mezők és Szerver Szinkron")

style = ttk.Style()
style.theme_use("default")

style.configure("Custom.Treeview",
                background="white",
                foreground="black",
                rowheight=25,
                fieldbackground="white",
                bordercolor="black",
                borderwidth=1,
                relief="solid",
                font=("Arial", 10))
style.map("Custom.Treeview",
          background=[("selected", "#004080")],
          foreground=[("selected", "white")])

style.configure("Custom.Treeview.Heading",
                font=("Arial", 10, "bold"),
                bordercolor="black",
                borderwidth=1,
                relief="solid")

frame_main = tk.Frame(root)
frame_main.pack(fill="both", expand=True)

tree = ttk.Treeview(frame_main, show="headings", selectmode="extended", style="Custom.Treeview")
vsb_main = ttk.Scrollbar(frame_main, orient="vertical", command=tree.yview)
hsb_main = ttk.Scrollbar(frame_main, orient="horizontal", command=tree.xview)
tree.configure(yscrollcommand=vsb_main.set, xscrollcommand=hsb_main.set)
vsb_main.pack(side="right", fill="y")
hsb_main.pack(side="bottom", fill="x")
tree.pack(fill="both", expand=True, padx=10, pady=10)

# === 100% PDF nyomtató gomb függvénye ===
def pdf_100_nyomtat():
    """
    Multi-oldalas A4 PDF generálása (2x2 felosztás), majd 100%-os nyomtatás.
    Windows alatt SumatraPDF-bel: -print-settings "noscale". Ha nincs Sumatra, megnyitjuk a PDF-et.
    """
    try:
        DPI = 300
        pages, A4_W, A4_H = build_pages_fullA4_from_selection(DPI=DPI)
        if not pages:
            return
        import tempfile, os, subprocess, sys
        # Ideiglenes PDF
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
        exe = None
        for c in candidates:
            if os.path.exists(c):
                exe = c; break
        if exe:
            # default printer, noscale, silent
            cmd = f'"{exe}" -print-to-default -print-settings "noscale" -silent "{path}"'
            try:
                subprocess.run(cmd, shell=True, check=True)
                messagebox.showinfo("Nyomtatás", "Elküldve a nyomtatóra (100%, noscale).")
                return
            except Exception:
                pass
        # Fallback: megnyitjuk a PDF-et, hogy kézzel tudd 100%-on nyomtatni
        try:
            os.startfile(path)
            messagebox.showinfo("Nyomtatás", "Megnyílt a PDF. Válaszd a 'Tényleges méret / 100%' beállítást a nyomtatón.")
        except Exception as e:
            messagebox.showwarning("Figyelem", f"Nem sikerült automatikusan megnyitni a PDF-et: {path}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        messagebox.showerror("Hiba", f"Hiba a PDF nyomtatás során: {e}")

# === A4 2x2 oldalépítő (100% PDF nyomtatáshoz) ===
def build_pages_fullA4_from_selection(DPI=300):
    """
    A4 (210x297mm) 2x2 teljes felosztás, margó nélkül, felirat nélkül.
    Visszatér: (pages_list, A4_W, A4_H)
    """
    selected = tree.selection()
    if not selected:
        messagebox.showwarning("Figyelem", "Válassz ki legalább egy sort a nyomtatáshoz!")
        return [], 0, 0

    def mm_to_px(mm):
        return int(round(mm / 25.4 * DPI))

    A4_W = mm_to_px(210)
    A4_H = mm_to_px(297)
    SLOT_W = A4_W // 2
    SLOT_H = A4_H // 2
    LEFT_MARGIN = 0
    TOP_MARGIN = 0
    INSET = 0

    # QR képek
    items = []
    for i in selected:
        sor = adatok[int(i)]
        az = sor.get("Azonosító", "") if isinstance(sor, dict) else sor["Azonosító"]
        qr_data = f"{SERVER_URL}/edit/{az}"
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_data); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        items.append((img, ""))

    while len(items) % 4 != 0:
        items.append((Image.new("RGB", (300, 300), "white"), ""))

    pages = []
    for start in range(0, len(items), 4):
        page = Image.new("RGB", (A4_W, A4_H), "white")
        draw = ImageDraw.Draw(page)
        positions = [
            (LEFT_MARGIN + 0 * SLOT_W, TOP_MARGIN + 0 * SLOT_H),
            (LEFT_MARGIN + 1 * SLOT_W, TOP_MARGIN + 0 * SLOT_H),
            (LEFT_MARGIN + 0 * SLOT_W, TOP_MARGIN + 1 * SLOT_H),
            (LEFT_MARGIN + 1 * SLOT_W, TOP_MARGIN + 1 * SLOT_H),
        ]
        for (qr_img, _), (x, y) in zip(items[start:start+4], positions):
            target_w = SLOT_W - 2 * INSET
            target_h = SLOT_H - 2 * INSET
            side = min(target_w, target_h)
            resample = getattr(Image, 'LANCZOS', Image.BICUBIC)
            qr_resized = qr_img.resize((side, side), resample)
            qr_x = x + (SLOT_W - side) // 2
            qr_y = y + (SLOT_H - side) // 2
            page.paste(qr_resized, (qr_x, qr_y))
        pages.append(page)

    return pages, A4_W, A4_H

frame = tk.Frame(root)
frame.pack(pady=10)

# --- Extra gombsor a nyomtatáshoz (külön frame-ben, hogy ne borítsa az elrendezést) ---
frame_4up = tk.Frame(root)
frame_4up.pack(pady=4)
tk.Button(frame_4up, text="A4 4× QR – PDF", command=pdf_100_nyomtat).pack()

tk.Button(frame, text="Új sor", command=lambda: sor_beviteli_ablak()).grid(row=0, column=0, padx=5)
tk.Button(frame, text="Módosítás", command=modositas).grid(row=0, column=1, padx=5)
tk.Button(frame, text="Törlés", command=torles).grid(row=0, column=2, padx=5)
tk.Button(frame, text="QR generálás", command=qr_generalas).grid(row=0, column=3, padx=5)
tk.Button(frame, text="Legördülők szerkesztése", command=szerkesztes_legordulok).grid(row=0, column=4, padx=5)
tk.Button(frame, text="Mezők szerkesztése", command=mezok_kezelese).grid(row=0, column=5, padx=5)
tk.Button(frame, text="Szinkronizálás szerverrel", command=sync_from_server).grid(row=0, column=6, padx=5)
tk.Button(frame, text="Mentés szerverre", command=sync_to_server).grid(row=0, column=7, padx=5)
tk.Button(frame, text="Lokális mentés", command=ment_local).grid(row=0, column=8, padx=5)
tk.Button(frame, text="Lokális betöltés", command=betolt_local).grid(row=0, column=9, padx=5)

zoom_frame = tk.Frame(root)
zoom_frame.pack(side="bottom", fill="x", padx=5, pady=5)
scale = tk.Scale(zoom_frame, from_=8, to=24, orient="horizontal", command=zoom, label="Zoom")
scale.set(10)
scale.pack(side="right")

# Inicializálás: frissítjük a Treeview-t (ha a szerver elérhető, megpróbáljuk szinkronizálni)
try:
    sync_from_server()
except Exception:
    update_tree()

root.mainloop()
