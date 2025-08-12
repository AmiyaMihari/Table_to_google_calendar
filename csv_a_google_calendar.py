# Programa para Calendar
import csv
import re
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os

SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12
}

def parse_spanish_date(text: str, default_year: int) -> datetime:
    s = (text or "").strip().lower()
    s = re.sub(r"\s+", " ", s)

    m = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$", s)
    if m:
        y, mo, d = map(int, m.groups())
        return datetime(y, mo, d)

    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", s)
    if m:
        d, mo, y = map(int, m.groups())
        return datetime(y, mo, d)

    m = re.match(r"^(\d{1,2})[/-](\d{1,2})$", s)
    if m:
        d, mo = map(int, m.groups())
        return datetime(default_year, mo, d)

    m = re.match(r"^(\d{1,2})\s*(?:de\s*)?([a-záéíóúñ]+)(?:\s*de\s*(\d{4}))?$", s, re.I)
    if m:
        d = int(m.group(1))
        mes = (m.group(2).replace("á","a").replace("é","e").replace("í","i")
               .replace("ó","o").replace("ú","u").replace("ñ","n"))
        mo = 9 if mes in ("septiembre","setiembre") else SPANISH_MONTHS.get(mes)
        if not mo:
            raise ValueError(f"Mes no reconocido: {m.group(2)}")
        y = int(m.group(3)) if m.group(3) else default_year
        return datetime(y, mo, d)

    m = re.match(r"^(\d{1,2})\s+([a-záéíóúñ]+)\s+(\d{4})$", s, re.I)
    if m:
        d = int(m.group(1))
        mes = (m.group(2).replace("á","a").replace("é","e").replace("í","i")
               .replace("ó","o").replace("ú","u").replace("ñ","n"))
        mo = SPANISH_MONTHS.get(mes)
        if not mo:
            raise ValueError(f"Mes no reconocido: {m.group(2)}")
        y = int(m.group(3))
        return datetime(y, mo, d)

    raise ValueError(f"No pude interpretar la fecha: '{text}'")

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
        self.geometry("680x480")
        self.resizable(False, False)

        self.csv_path = tk.StringVar()
        self.csv_full_path = None
        self.default_year = tk.StringVar(value=str(datetime.now().year))
        self.date_format = tk.StringVar(value="DD/MM/YYYY")  # predeterminado
        self.headers = []

        lf1 = ttk.LabelFrame(self, text="1) Selecciona el CSV de origen")
        lf1.pack(fill="x", padx=12, pady=(12,6))
        ttk.Entry(lf1, textvariable=self.csv_path, state="readonly").pack(side="left", fill="x", expand=True, padx=8, pady=8)
        ttk.Button(lf1, text="Buscar…", command=self.pick_csv).pack(side="right", padx=8, pady=8)

        row = ttk.Frame(self); row.pack(fill="x", padx=12, pady=6)
        ttk.Label(row, text="Año:").pack(side="left")
        ttk.Entry(row, width=8, textvariable=self.default_year).pack(side="left", padx=(6,18))
        ttk.Label(row, text="Formato de fecha para el CSV:").pack(side="left")
        ttk.OptionMenu(row, self.date_format, "DD/MM/YYYY", "DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD").pack(side="left", padx=6)

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

        btn_row = ttk.Frame(self); btn_row.pack(fill="x", padx=12, pady=12)
        ttk.Button(btn_row, text="Convertir a CSV (Google Calendar)", command=self.convert, width=32)\
            .pack(side="right")

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

        # Leer encabezados
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                sample = f.read(4096)
                f.seek(0)
                delimiter = "," if sample.count(",") >= sample.count(";") else ";"
                reader = csv.reader(f, delimiter=delimiter)
                self.headers = next(reader)
        except Exception as e:
            messagebox.showerror("Error al leer CSV", f"No pude abrir el archivo:\n{e}")
            return

        # Cargar headers en los combos
        for cmb in (self.cmb_unidad, self.cmb_nombre, self.cmb_desc, self.cmb_fecha):
            cmb["values"] = self.headers

        # ⭐ Autómapeo restaurado
        self.cmb_unidad.set(self._auto_pick(self.headers, "unidad", "curso", "modulo", "módulo"))
        self.cmb_nombre.set(self._auto_pick(self.headers, "nombre", "actividad", "tarea"))
        self.cmb_desc.set(self._auto_pick(self.headers, "descripcion", "descripción", "detalle"))
        self.cmb_fecha.set(self._auto_pick(self.headers, "fecha de entrega", "fecha", "entrega", "due", "vence", "deadline"))

        self.info.config(text=f"Se detectaron {len(self.headers)} columnas. Revisa el mapeo antes de convertir.")

    def convert(self):
        if not self.csv_full_path:
            messagebox.showwarning("Falta CSV", "Primero selecciona un archivo.")
            return
        try:
            year = int(self.default_year.get())
            if not (1900 <= year <= 3000):
                raise ValueError
        except:
            messagebox.showwarning("Año inválido", "Indica un año válido (ej. 2025).")
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
                sample = fin.read(4096)
                fin.seek(0)
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
                            dt = parse_spanish_date(fecha_raw, year)
                            start = fmt_date(dt, self.date_format.get())

                            unidad = (row.get(col_unidad, "") or "").strip()
                            nombre = (row.get(col_nombre, "") or "").strip()
                            desc = (row.get(col_desc, "") or "").strip()
                            subject = f"{unidad} - {nombre}".strip(" -")

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

if __name__ == "__main__":
    App().mainloop()
