import csv
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import sys
import webbrowser

# ---- Dependencias para Excel ----
HAS_PANDAS = True
try:
    import pandas as pd
except Exception:
    HAS_PANDAS = False

# ---- Pillow para JPG/JPEG ----
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except Exception:
    HAS_PIL = False

# ---- Utilidad para recursos (PyInstaller) ----
def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)

# ---- Fechas ----
def parse_ddmmyyyy(text: str) -> datetime:
    """Convierte fecha con formato DD/MM/AAAA a datetime."""
    return datetime.strptime((text or "").strip(), "%d/%m/%Y")

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
        self.title("CSV/Excel → Google Calendar (All-day)")
        self.geometry("760x700")
        self.resizable(False, False)

        self.file_label_var = tk.StringVar(value="")
        self.input_full_path = None
        self.date_format = tk.StringVar(value="DD/MM/YYYY")  # export predeterminada
        self.headers = []
        self.is_excel = False
        self.sheets = []
        self.selected_sheet = tk.StringVar(value="")
        self.excel_engine = "openpyxl"  # sólo .xlsx/.xlsm

        # 1) Selección archivo
        lf1 = ttk.LabelFrame(self, text="1) Selecciona tu archivo (CSV o Excel)")
        lf1.pack(fill="x", padx=12, pady=(12,6))
        ttk.Entry(lf1, textvariable=self.file_label_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=8, pady=8
        )
        ttk.Button(lf1, text="Buscar…", command=self.pick_file).pack(side="right", padx=8, pady=8)

        # Si es Excel, elegir hoja
        self.sheet_frame = ttk.Frame(self); self.sheet_frame.pack(fill="x", padx=12, pady=(0,6))
        ttk.Label(self.sheet_frame, text="Hoja:").pack(side="left")
        self.sheet_combo = ttk.Combobox(self.sheet_frame, state="readonly", textvariable=self.selected_sheet, width=40)
        self.sheet_combo.pack(side="left", padx=8)
        self.sheet_frame.pack_forget()  # oculto hasta detectar Excel

        # 2) Formato de fecha de salida
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
        self._map_row("Fecha de entrega (DD/MM/AAAA):", self.cmb_fecha)

        self.info = ttk.Label(self, text="Carga un archivo para habilitar el mapeo.", foreground="#555")
        self.info.pack(fill="x", padx=12, pady=6)

        # 4) Convertir
        btn_row = ttk.Frame(self); btn_row.pack(fill="x", padx=12, pady=12)
        ttk.Button(btn_row, text="Convertir a CSV (Google Calendar)", command=self.convert, width=32)\
            .pack(side="right")

        # 5) Imagen y créditos
        self._add_image_and_credits()

    # ------------- UI helpers -------------
    def _map_row(self, label, combo):
        r = ttk.Frame(self.map_frame); r.pack(fill="x", padx=8, pady=5)
        ttk.Label(r, text=label, width=32, anchor="w").pack(side="left")
        combo.pack(side="left", fill="x", expand=True)

    def _auto_pick(self, headers, *candidatos):
        for c in candidatos:
            for h in headers:
                if c.lower() in h.lower():
                    return h
        return headers[0] if headers else ""

    # ------------- File loading -------------
    def pick_file(self):
        # Mostrar CSV y Excel por defecto (primera opción) para que no se oculte ninguno
        path = filedialog.askopenfilename(
            filetypes=[
                ("Excel/CSV", "*.xlsx *.xlsm *.csv"),
                ("Excel (*.xlsx; *.xlsm)", "*.xlsx *.xlsm"),
                ("CSV (*.csv)", "*.csv"),
                ("Todos", "*.*"),
            ]
        )
        if not path:
            return
        self.input_full_path = path
        self.file_label_var.set(os.path.basename(path))
        ext = os.path.splitext(path)[1].lower()
        self.is_excel = ext in (".xlsx", ".xlsm")  # .xls no soportado (usa guardar como .xlsx)

        if self.is_excel and not HAS_PANDAS:
            messagebox.showerror(
                "Falta dependencia",
                "Para leer archivos Excel necesitas instalar:\n\npip install pandas openpyxl"
            )
            self.clear_headers()
            return

        try:
            if self.is_excel:
                # Mostrar selector de hoja
                self.sheets = self._get_excel_sheets(path)
                if not self.sheets:
                    raise ValueError("No se detectaron hojas en el Excel. Verifica que no esté vacío/oculto.")
                self.sheet_frame.pack(fill="x", padx=12, pady=(0,6))
                self.sheet_combo["values"] = self.sheets
                self.selected_sheet.set(self.sheets[0])

                # Cargar headers de la primera hoja
                df = pd.read_excel(path, sheet_name=self.selected_sheet.get(), dtype=str, engine=self.excel_engine)
                self.headers = list(df.columns.astype(str))
            else:
                self.sheet_frame.pack_forget()
                # CSV: detectar delimitador simple y leer headers
                with open(path, "r", encoding="utf-8-sig", newline="") as f:
                    sample = f.read(4096); f.seek(0)
                    delimiter = "," if sample.count(",") >= sample.count(";") else ";"
                    reader = csv.reader(f, delimiter=delimiter)
                    self.headers = next(reader)
        except Exception as e:
            messagebox.showerror("Error al abrir", f"No pude abrir el archivo:\n{e}")
            self.clear_headers()
            return

        # Poner headers en combos y autómapeo
        for cmb in (self.cmb_unidad, self.cmb_nombre, self.cmb_desc, self.cmb_fecha):
            cmb["values"] = self.headers

        self.cmb_unidad.set(self._auto_pick(self.headers, "unidad", "curso", "modulo", "módulo"))
        self.cmb_nombre.set(self._auto_pick(self.headers, "nombre", "actividad", "tarea"))
        self.cmb_desc.set(self._auto_pick(self.headers, "descripcion", "descripción", "detalle"))
        self.cmb_fecha.set(self._auto_pick(self.headers, "fecha de entrega", "fecha", "entrega", "due", "vence", "deadline"))

        self.info.config(text=f"Se detectaron {len(self.headers)} columnas. Revisa el mapeo antes de convertir.")

        # Al cambiar de hoja, recargar headers
        if self.is_excel:
            self.sheet_combo.bind("<<ComboboxSelected>>", self._on_sheet_change)

    def _on_sheet_change(self, _evt):
        if not (self.is_excel and HAS_PANDAS and self.input_full_path):
            return
        try:
            df = pd.read_excel(self.input_full_path, sheet_name=self.selected_sheet.get(), dtype=str, engine=self.excel_engine)
            self.headers = list(df.columns.astype(str))
        except Exception as e:
            messagebox.showerror("Error de hoja", f"No pude leer la hoja seleccionada:\n{e}")
            return

        for cmb in (self.cmb_unidad, self.cmb_nombre, self.cmb_desc, self.cmb_fecha):
            cmb["values"] = self.headers

        # Reaplicar autómapeo si aún no hay valor
        if not self.cmb_unidad.get():
            self.cmb_unidad.set(self._auto_pick(self.headers, "unidad", "curso", "modulo", "módulo"))
        if not self.cmb_nombre.get():
            self.cmb_nombre.set(self._auto_pick(self.headers, "nombre", "actividad", "tarea"))
        if not self.cmb_desc.get():
            self.cmb_desc.set(self._auto_pick(self.headers, "descripcion", "descripción", "detalle"))
        if not self.cmb_fecha.get():
            self.cmb_fecha.set(self._auto_pick(self.headers, "fecha de entrega", "fecha", "entrega", "due", "vence", "deadline"))

    def _get_excel_sheets(self, path):
        try:
            xls = pd.ExcelFile(path, engine=self.excel_engine)
            return xls.sheet_names
        except Exception as e:
            raise RuntimeError(f"No pude leer las hojas del Excel ({type(e).__name__}: {e})")

    def clear_headers(self):
        self.headers = []
        for cmb in (self.cmb_unidad, self.cmb_nombre, self.cmb_desc, self.cmb_fecha):
            cmb.set("")
            cmb["values"] = []

    # ------------- Convert -------------
    def convert(self):
        if not self.input_full_path:
            messagebox.showwarning("Falta archivo", "Primero selecciona un archivo CSV o Excel.")
            return

        col_unidad = self.cmb_unidad.get().strip()
        col_nombre = self.cmb_nombre.get().strip()
        col_desc = self.cmb_desc.get().strip()
        col_fecha = self.cmb_fecha.get().strip()
        if not all([col_unidad, col_nombre, col_desc, col_fecha]):
            messagebox.showwarning("Mapeo incompleto", "Completa el mapeo de columnas.")
            return

        base = os.path.splitext(os.path.basename(self.input_full_path))[0]
        suggested = f"{base}_calendar.csv"
        out_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=suggested,
            filetypes=[("CSV", "*.csv"), ("Todos", "*.*")]
        )
        if not out_path:
            return

        # Cargar datos completos según tipo
        try:
            if self.is_excel:
                if not HAS_PANDAS:
                    raise RuntimeError("Faltan pandas/openpyxl para leer Excel.")
                df = pd.read_excel(self.input_full_path, sheet_name=self.selected_sheet.get(), dtype=str, engine=self.excel_engine)
                data_iter = df.to_dict(orient="records")
            else:
                with open(self.input_full_path, "r", encoding="utf-8-sig", newline="") as fin:
                    sample = fin.read(4096); fin.seek(0)
                    delimiter = "," if sample.count(",") >= sample.count(";") else ";"
                    reader = csv.DictReader(fin, delimiter=delimiter)
                    data_iter = list(reader)
        except Exception as e:
            messagebox.showerror("Error al leer", f"Ocurrió un problema al procesar el archivo:\n{e}")
            return

        total, ok, errores = 0, 0, []
        fieldnames = [
            "Subject", "Start Date", "Start Time",
            "End Date", "End Time",
            "All Day Event", "Description", "Location", "Private"
        ]

        try:
            with open(out_path, "w", encoding="utf-8-sig", newline="") as fout:
                writer = csv.DictWriter(fout, fieldnames=fieldnames)
                writer.writeheader()

                for i, row in enumerate(data_iter, start=2):
                    total += 1
                    try:
                        fecha_raw = str((row.get(col_fecha, "") or "")).strip()
                        if not fecha_raw:
                            raise ValueError("fecha vacía")
                        dt = parse_ddmmyyyy(fecha_raw)
                        start = fmt_date(dt, self.date_format.get())

                        unidad = str((row.get(col_unidad, "") or "")).strip()
                        nombre = str((row.get(col_nombre, "") or "")).strip()
                        desc = str((row.get(col_desc, "") or "")).strip()
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
            messagebox.showerror("Error al guardar", f"No pude escribir el CSV de salida:\n{e}")
            return

        msg = f"Listo. Procesadas {total} filas, creados {ok} eventos.\nArchivo: {os.path.basename(out_path)}"
        if errores:
            msg += f"\n\nErrores en {len(errores)} filas (primeras 10):\n- " + "\n- ".join(errores[:10])
        messagebox.showinfo("Conversión completada", msg)

    # ------------- Imagen + créditos -------------
    def _add_image_and_credits(self):
        container = ttk.Frame(self)
        container.pack(fill="x", padx=12, pady=(20, 10))

        # Imagen (gato2.jpeg) redimensionada a 300 px de ancho
        if HAS_PIL:
            try:
                img_path = resource_path("gato2.jpeg")
                img = Image.open(img_path)
                max_w = 200
                if img.width > max_w:
                    ratio = max_w / float(img.width)
                    img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)

                self.gato_img = ImageTk.PhotoImage(img)
                img_label = ttk.Label(container, image=self.gato_img)
                img_label.pack()
            except Exception:
                ttk.Label(container, text="(No se pudo cargar gato2.jpeg)", foreground="red").pack()
        else:
            ttk.Label(container, text="(Pillow no instalado; instala con: pip install pillow)", foreground="red").pack()

        # Enlace clicable
        url = "https://github.com/AmiyaMihari"
        link = ttk.Label(container, text=f"Créditos: {url}", foreground="blue", cursor="hand2")
        link.pack(pady=(6, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open_new_tab(url))

if __name__ == "__main__":
    App().mainloop()
