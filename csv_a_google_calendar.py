import csv
import re
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os

# -------------------- Fechas --------------------
SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12
}

def parse_spanish_date(text: str, default_year: int) -> datetime:
    """
    Acepta:
      - '21 de agosto', '08 septiembre 2025'
      - '21/08/2025', '21-08-2025'
      - '2025-08-21'
      - '08/09' (usa default_year)
    Devuelve datetime a medianoche o lanza ValueError.
    """
    s = (text or "").strip().lower()
    s = re.sub(r"\s+", " ", s)

    # yyyy-mm-dd o yyyy/mm/dd
    m = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$", s)
    if m:
        y, mo, d = map(int, m.groups())
        return datetime(y, mo, d)

    # dd-mm-yyyy o dd/mm/yyyy
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", s)
    if m:
        d, mo, y = map(int, m.groups())
        return datetime(y, mo, d)

    # dd-mm o dd/mm (sin año)
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})$", s)
    if m:
        d, mo = map(int, m.groups())
        return datetime(default_year, mo, d)

    # 'dd (de) mes (de yyyy)?'
    m = re.match(r"^(\d{1,2})\s*(?:de\s*)?([a-záéíóúñ]+)(?:\s*de\s*(\d{4}))?$", s, re.I)
    if m:
        d = int(m.group(1))
        mes = (m.group(2)
               .replace("á","a").replace("é","e").replace("í","i")
               .replace("ó","o").replace("ú","u").replace("ñ","n"))
        mo = 9 if mes in ("septiembre","setiembre") else SPANISH_MONTHS.get(mes)
        if not mo:
            raise ValueError(f"Mes no reconocido: {m.group(2)}")
        y = int(m.group(3)) if m.group(3) else default_year
        return datetime(y, mo, d)

    # 'dd mes yyyy' (sin "de")
    m = re.match(r"^(\d{1,2})\s+([a-záéíóúñ]+)\s+(\d{4})$", s, re.I)
    if m:
        d = int(m.group(1))
        mes = (m.group(2)
               .replace("á","a").replace("é","e").replace("í","i")
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
    return dt.strftime("%m/%d/%Y")  # fallback

# -------------------- GUI --------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CSV → Google Calendar (All-day)")
        self.geometry("680x480")
        self.resizable(False, False)

        self.csv_path = tk.StringVar()
        self.default_year = tk.StringVar(value=str(datetime.now().year))
        self.date_format = tk.StringVar(value="MM/DD/YYYY")  # Google en inglés usa este
        self.headers = []

        # 1) Selección CSV
        lf1 = ttk.LabelFrame(self, text="1) Selecciona el CSV de origen")
        lf1.pack(fill="x", padx=12, pady=(12,6))
        ttk.Entry(lf1, textvariable=self.csv_path, state="readonly").pack(side="left", fill="x", expand=True, padx=8, pady=8)
        ttk.Button(lf1, text="Buscar…", command=self.pick_csv).pack(side="right", padx=8, pady=8)

        # 2) Año y formato de fecha
        row = ttk.Frame(self); row.pack(fill="x", padx=12, pady=6)
        ttk.Label(row, text="Año por defecto (si la fecha no trae año):").pack(side="left")
        ttk.Entry(row, width=8, textvariable=self.default_year).pack(side="left", padx=(6,18))
        ttk.Label(row, text="Formato de fecha para el CSV:").pack(side="left")
        ttk.OptionMenu(row, self.date_format, "MM/DD/YYYY", "MM/DD/YYYY", "DD/MM/YYYY", "YYYY-MM-DD").pack(side="left", padx=6)

        # 3) Mapeo de columnas
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

        # 4) Botón convertir
        btn_row = ttk.Frame(self); btn_row.pack(fill="x", padx=12, pady=12)
        ttk.Button(btn_row, text="Convertir a CSV (Google Calendar)", command=self.convert, width=32)\
            .pack(side="right")

        try:
            ttk.Style().theme_use("clam")
        except:
            pass

    def _map_row(self, label, combo):
        r = ttk.Frame(self.map_frame); r.pack(fill="x", padx=8, pady=5)
        ttk.Label(r, text=label, width=28, anchor="w").pack(side="left")
        combo.pack(side="left", fill="x", expand=True)

    def pick_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv;*.CSV"), ("Todos", "*.*")])
        if not path:
            return
        self.csv_path.set(path)

        # Leer encabezados
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                sample = f.read(4096)
                f.seek(0)
                # Detección sencilla de delimitador
                delimiter = "," if sample.count(",") >= sample.count(";") else ";"
                reader = csv.reader(f, delimiter=delimiter)
                self.headers = next(reader)
        except Exception as e:
            messagebox.showerror("Error al leer CSV", f"No pude abrir el archivo:\n{e}")
            return

        for cmb in (self.cmb_unidad, self.cmb_nombre, self.cmb_desc, self.cmb_fecha):
            cmb["values"] = self.headers

        def auto_pick(*candidatos):
            for c in candidatos:
                for h in self.headers:
                    if c.lower() in h.lower():
                        return h
            return self.headers[0] if self.headers else ""

        self.cmb_unidad.set(auto_pick("unidad", "curso", "modulo"))
        self.cmb_nombre.set(auto_pick("nombre", "actividad", "tarea"))
        self.cmb_desc.set(auto_pick("descripcion", "descripción", "detalle"))
        self.cmb_fecha.set(auto_pick("fecha de entrega", "fecha", "entrega", "due"))

        self.info.config(text=f"Se detectaron {len(self.headers)} columnas. Revisa el mapeo antes de convertir.")

    def convert(self):
        if not self.csv_path.get():
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

        # Salida con *_calendar.csv
        base = os.path.splitext(os.path.basename(self.csv_path.get()))[0]
        suggested = f"{base}_calendar.csv"
        out_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=suggested,
            filetypes=[("CSV", "*.csv")]
        )
        if not out_path:
            return

        # Leer origen y escribir destino
        total, ok, errores = 0, 0, []
        # Intentar detectar delimitador de entrada otra vez
        try:
            with open(self.csv_path.get(), "r", encoding="utf-8-sig", newline="") as fin:
                sample = fin.read(4096)
                fin.seek(0)
                delimiter = "," if sample.count(",") >= sample.count(";") else ";"
                reader = csv.DictReader(fin, delimiter=delimiter)

                # CSV de Google Calendar (cabeceras típicas)
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
                            end = start  # evento de 1 día

                            unidad = (row.get(col_unidad, "") or "").strip()
                            nombre = (row.get(col_nombre, "") or "").strip()
                            desc = (row.get(col_desc, "") or "").strip()

                            subject = f"{unidad} - {nombre}".strip(" -")
                            writer.writerow({
                                "Subject": subject or "Actividad",
                                "Start Date": start,
                                "Start Time": "",
                                "End Date": end,
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

        msg = f"Listo. Se procesaron {total} filas y se generaron {ok} eventos.\n\nArchivo: {os.path.basename(out_path)}"
        if errores:
            msg += f"\n\nCon errores en {len(errores)} filas (primeras 10):\n- " + "\n- ".join(errores[:10])
        messagebox.showinfo("Conversión completada", msg)

if __name__ == "__main__":
    # Estilos de Tk en Windows/Linux se ven mejor con 'clam'
    try:
        ttk.Style().theme_use("clam")
    except:
        pass
    App().mainloop()
