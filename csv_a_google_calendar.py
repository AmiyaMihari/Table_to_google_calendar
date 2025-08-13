# al inicio del archivo (junto a imports)
import sys, os

import csv
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import webbrowser

# Para recursos empaquetados
def resource_path(relative_path: str) -> str:
    # Cuando está empaquetado, PyInstaller define _MEIPASS
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)

# Intentar cargar Pillow para JPG
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

def parse_ddmmyyyy(text: str) -> datetime:
    """Convierte fecha con formato DD/MM/AAAA a datetime."""
    return datetime.strptime(text.strip(), "%d/%m/%Y")

def fmt_date(dt: datetime, pattern: str) -> str:
    if pattern == "MM/DD/YYYY":
        return dt.strftime("%m/%d/%Y")
    if pattern == "DD/MM/YYYY":
        return dt.strftime("%d/%m/%Y")
    if pattern == "YYYY-MM-DD":
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%d/%m/%Y")

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CSV → Google Calendar (All-day)")
        self.geometry("700x650")  # un poco más alta para imagen y créditos
        self.resizable(False, False)

        self.csv_path = tk.StringVar()
        self.csv_full_path = None
        self.date_format = tk.StringVar(value="DD/MM/YYYY")  # export predeterminada
        self.headers = []

        # 1) Selección CSV
        lf1 = ttk.LabelFrame(self, text="1) Selecciona el CSV de origen")
        lf1.pack(fill="x", padx=12, pady=(12,6))
        ttk.Entry(lf1, textvariable=self.csv_path, state="readonly").pack(
            side="left", fill="x", expand=True, padx=8, pady=8
        )
        ttk.Button(lf1, text="Buscar…", command=self.pick_csv).pack(side="right", padx=8, pady=8)

        # 2) Formato de fecha salida
        row = ttk.Frame(self); row.pack(fill="x", padx=12, pady=6)
        ttk.Label(row, text="Formato de fecha para el CSV de salida:").pack(side="left")
        ttk.OptionMenu(row, self.date_format, "DD/MM/YYYY",
                       "DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD").pack(side="left", padx=6)

        # 3) Mapeo columnas
        self.map_frame = ttk.LabelFrame(self, text="2) Mapea tus columnas")
        self.map_frame.pack(fill="x", padx=12, pady=6)
        self.cmb_unidad = ttk.Combobox(self.map_frame, state="readonly")
        self.cmb_nombre = ttk.Combobox(self.map_frame, state="readonly")
        self.cmb_desc = ttk.Combobox(self.map_frame, state="readonly")
        self.cmb_fecha = ttk.Combobox(self.map_frame, state="readonly")
        self._map_row("Unidad / Curso:", self.cmb_unidad)
        self._map_row("Nombre de la actividad:", self.cmb_nombre)
        self._map_row("Descripción:", self.cmb_desc)
        self._map_row("Fecha de entrega:", self.cmb_fecha)

        self.info = ttk.Label(self, text="Carga un CSV para habilitar el mapeo.", foreground="#555")
        self.info.pack(fill="x", padx=12, pady=6)

        # 4) Convertir
        btn_row = ttk.Frame(self); btn_row.pack(fill="x", padx=12, pady=12)
        ttk.Button(btn_row, text="Convertir a CSV (Google Calendar)", command=self.convert, width=32)\
            .pack(side="right")

        # 5) Imagen (gato.jpg) y créditos clicables
        self._add_image_and_credits()

    def _map_row(self, label, combo):
        r = ttk.Frame(self.map_frame); r.pack(fill="x", padx=8, pady=5)
        ttk.Label(r, text=label, width=28, anchor="w").pack(side="left")
        combo.pack(side="left", fill="x", expand=True)

    def _auto_pick(self, headers, *candidatos):
        for c in candidatos:
            for h in headers:
                if c.lower() in h.lower():
                    return h
        return headers[0] if headers else ""

    def pick_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv;*.CSV"), ("Todos", "*.*")])
        if not path:
            return
        self.csv_full_path = path
        self.csv_path.set(os.path.basename(path))  # muestra nombre en la barra

        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                sample = f.read(4096); f.seek(0)
                delimiter = "," if sample.count(",") >= sample.count(";") else ";"
                reader = csv.reader(f, delimiter=delimiter)
                self.headers = next(reader)
        except Exception as e:
            messagebox.showerror("Error al leer CSV", f"No pude abrir el archivo:\n{e}")
            return

        for cmb in (self.cmb_unidad, self.cmb_nombre, self.cmb_desc, self.cmb_fecha):
            cmb["values"] = self.headers

        self.cmb_unidad.set(self._auto_pick(self.headers, "unidad", "curso", "modulo", "módulo"))
        self.cmb_nombre.set(self._auto_pick(self.headers, "nombre", "actividad", "tarea"))
        self.cmb_desc.set(self._auto_pick(self.headers, "descripcion", "descripción", "detalle"))
        self.cmb_fecha.set(self._auto_pick(self.headers, "fecha de entrega", "fecha", "entrega", "due", "vence", "deadline"))

        self.info.config(text=f"Se detectaron {len(self.headers)} columnas. Revisa el mapeo antes de convertir.")

    def convert(self):
        if not self.csv_full_path:
            messagebox.showwarning("Falta CSV", "Primero selecciona un archivo.")
            return

        col_unidad = self.cmb_unidad.get().strip()
        col_nombre = self.cmb_nombre.get().strip()
        col_desc = self.cmb_desc.get().strip()
        col_fecha = self.cmb_fecha.get().strip()
        if not all([col_unidad, col_nombre, col_desc, col_fecha]):
            messagebox.showwarning("Mapeo incompleto", "Completa el mapeo de columnas.")
            return

        base = os.path.splitext(os.path.basename(self.csv_full_path))[0]
        suggested = f"{base}_calendar.csv"
        out_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=suggested,
            filetypes=[("CSV", "*.csv")]
        )
        if not out_path:
            return

        total, ok, errores = 0, 0, []
        try:
            with open(self.csv_full_path, "r", encoding="utf-8-sig", newline="") as fin:
                sample = fin.read(4096); fin.seek(0)
                delimiter = "," if sample.count(",") >= sample.count(";") else ";"
                reader = csv.DictReader(fin, delimiter=delimiter)

                fieldnames = [
                    "Subject", "Start Date", "Start Time",
                    "End Date", "End Time",
                    "All Day Event", "Description", "Location", "Private"
                ]
                with open(out_path, "w", encoding="utf-8-sig", newline="") as fout:
                    writer = csv.DictWriter(fout, fieldnames=fieldnames)
                    writer.writeheader()
                    for i, row in enumerate(reader, start=2):
                        total += 1
                        try:
                            fecha_raw = (row.get(col_fecha, "") or "").strip()
                            if not fecha_raw:
                                raise ValueError("fecha vacía")
                            dt = parse_ddmmyyyy(fecha_raw)
                            start = fmt_date(dt, self.date_format.get())

                            unidad = (row.get(col_unidad, "") or "").strip()
                            nombre = (row.get(col_nombre, "") or "").strip()
                            desc = (row.get(col_desc, "") or "").strip()
                            subject = f"Unidad {unidad} - {nombre}".strip(" -")

                            writer.writerow({
                                "Subject": subject or "Actividad",
                                "Start Date": start,
                                "Start Time": "",
                                "End Date": start,
                                "End Time": "",
                                "All Day Event": "True",
                                "Description": desc,
                                "Location": "",
                                "Private": ""
                            })
                            ok += 1
                        except Exception as e:
                            errores.append(f"Fila {i}: {e}")
        except Exception as e:
            messagebox.showerror("Error", f"Ocurrió un problema:\n{e}")
            return

        msg = f"Listo. Procesadas {total} filas, creados {ok} eventos.\nArchivo: {os.path.basename(out_path)}"
        if errores:
            msg += f"\n\nErrores en {len(errores)} filas (primeras 10):\n- " + "\n- ".join(errores[:10])
        messagebox.showinfo("Conversión completada", msg)

    def _add_image_and_credits(self):
        """Inserta gato.jpg y un enlace clicable de créditos."""
        container = ttk.Frame(self)
        container.pack(fill="x", padx=12, pady=(20, 10))

        # Imagen JPG con Pillow (si está disponible)
        if PIL_AVAILABLE:
            try:
                img_path = resource_path("gato2.jpeg")
                img = Image.open(img_path)

                # Escalar si es muy grande (máx 600 px de ancho)
                max_w = 200
                if img.width > max_w:
                    ratio = max_w / float(img.width)
                    img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)

                self.gato_img = ImageTk.PhotoImage(img)  # mantener referencia
                img_label = ttk.Label(container, image=self.gato_img)
                img_label.pack()
            except Exception:
                ttk.Label(container, text="(No se pudo cargar gato.jpg)", foreground="red").pack()
        else:
            ttk.Label(container, text="(Pillow no instalado; instala con: pip install pillow)", foreground="red").pack()

        # Enlace clicable
        url = "https://github.com/AmiyaMihari"
        link = ttk.Label(container, text=f"Créditos: {url}", foreground="blue", cursor="hand2")
        link.pack(pady=(6, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open_new_tab(url))

if __name__ == "__main__":
    App().mainloop()
