#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, json, re, sys, time
from typing import List, Dict, Any, Optional, Tuple
from string import Template
import pandas as pd

# ========================= PROMPTS =========================
# Pedimos OBJETO con clave "rows" para mayor estabilidad.
PROMPT_TMPL = Template("""
Eres un extractor estructurado. Convierte el texto a JSON válido con ESTA forma exacta:

{
  "rows": [
    {
      "unidad": <int>,
      "actividad": <string>,
      "fecha_entrega": <string>,
      "descripcion": <string>,
      "valor_porcentaje": <string>
    }
  ]
}

Reglas:
- Responde SOLO JSON válido (sin comentarios, ni texto extra).
- El texto ya viene segmentado para UNA SOLA unidad y/o actividad.
- Si falta un campo, usa "" (cadena vacía), excepto "unidad": si no se puede inferir, deja null.
- NO inventes datos.
- Mantén el idioma original del texto.

Texto:
<<<
$texto
>>>
SALIDA:
""")

# ==================== UTILIDADES LIMPIEZA ==================
SPANISH_MONTHS = {
    "ene": 1, "enero": 1,
    "feb": 2, "febrero": 2,
    "mar": 3, "marzo": 3,
    "abr": 4, "abril": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "junio": 6,
    "jul": 7, "julio": 7,
    "ago": 8, "agosto": 8,
    "sep": 9, "sept": 9, "septiembre": 9,
    "oct": 10, "octubre": 10,
    "nov": 11, "noviembre": 11,
    "dic": 12, "diciembre": 12,
}

def normalize_date_es(s: str) -> str:
    if not s:
        return s
    t = s.strip().lower()
    t = re.sub(r'\s+', ' ', t)
    m = re.search(r'(\d{1,2})\s*[-/ ]\s*([a-záéíóú\.]+)\s*[-/ ]\s*(\d{2,4})', t)
    if not m:
        m2 = re.search(r'(\d{1,2})\s*[-/ ]\s*(\d{1,2})\s*[-/ ]\s*(\d{2,4})', t)
        if m2:
            d, mo, y = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
            y = 2000 + y if y < 100 else y
            try:
                return f"{y:04d}-{mo:02d}-{d:02d}"
            except:
                return s
        return s
    d = int(m.group(1))
    mon = m.group(2).replace('.', '')
    y = int(m.group(3))
    mon = (mon
           .replace('á','a')
           .replace('é','e')
           .replace('í','i')
           .replace('ó','o')
           .replace('ú','u')).strip()
    mm = SPANISH_MONTHS.get(mon) or SPANISH_MONTHS.get(mon[:3])
    if not mm:
        return s
    if y < 100:
        y = 2000 + y
    try:
        return f"{y:04d}-{mm:02d}-{d:02d}"
    except:
        return s

def clean_valor_percent(x: str) -> Optional[int]:
    if not x:
        return None
    s = re.sub(r'[^\d]', '', x)
    return int(s) if s.isdigit() else None

def coerce_unidad(x) -> Optional[int]:
    if x is None:
        return None
    if isinstance(x, int):
        return x
    m = re.search(r'\d+', str(x))
    return int(m.group()) if m else None

# ==================== PARSEO JSON ROBUSTO ==================
def extract_first_json_array(text: str) -> List[Dict[str, Any]]:
    start = text.find('[')
    if start == -1:
        raise ValueError("No se encontró ningún '[' en la respuesta para extraer un array.")
    open_br = 0
    end = None
    for i in range(start, len(text)):
        ch = text[i]
        if ch == '[':
            open_br += 1
        elif ch == ']':
            open_br -= 1
            if open_br == 0:
                end = i + 1
                break
    if end is None:
        raise ValueError("No se pudo equilibrar el array JSON.")
    arr_str = text[start:end]
    data = json.loads(arr_str)
    if not isinstance(data, list):
        raise ValueError("El bloque extraído no es un array JSON.")
    return data

def parse_rows_from_content(content: str) -> List[Dict[str, Any]]:
    try:
        obj = json.loads(content)
        if isinstance(obj, dict) and "rows" in obj and isinstance(obj["rows"], list):
            return obj["rows"]
        if isinstance(obj, list):
            return obj
    except Exception:
        pass
    return extract_first_json_array(content)

# ======================== OLLAMA ===========================
def call_ollama_chunk(texto: str, model: str, temperature: float = 0.1, retries: int = 3) -> List[Dict[str, Any]]:
    try:
        import ollama
    except ModuleNotFoundError:
        print("ERROR: falta instalar la librería Python 'ollama'.\nSolución: pip install ollama", file=sys.stderr)
        sys.exit(1)

    prompt = PROMPT_TMPL.substitute(texto=texto)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            res = ollama.chat(
                model=model,
                messages=[
                    {"role": "system", "content": "Devuelve SOLO JSON válido. Si dudases, devuelve {'rows': []}."},
                    {"role": "user", "content": prompt}
                ],
                options={
                    "temperature": max(0.0, temperature - 0.05 * (attempt - 1)),
                    "num_ctx": 4096
                },
                format="json",
            )
            content = res["message"]["content"]
            rows = parse_rows_from_content(content)
            norm = []
            for it in rows:
                norm.append({
                    "unidad": it.get("unidad"),
                    "actividad": it.get("actividad", "") or "",
                    "fecha_entrega": it.get("fecha_entrega", "") or "",
                    "descripcion": it.get("descripcion", "") or "",
                    "valor_porcentaje": it.get("valor_porcentaje", "") or "",
                })
            return norm
        except Exception as e:
            last_err = e
            time.sleep(0.2)
    raise ValueError(f"Fallo al parsear JSON del modelo: {last_err}")

# =============== SEGMENTADOR POR “UNIDAD …” ===============
UNIDAD_RE = re.compile(r'(?:^|\n)\s*Unidad\s+(\d+)\b', re.IGNORECASE)

def split_by_unidad(texto: str) -> List[Tuple[Optional[int], str]]:
    """
    Devuelve lista de (unidad_detectada, bloque_texto) por cada sección.
    Si no detecta 'Unidad N', devuelve el texto completo como un solo bloque.
    """
    indices = []
    for m in UNIDAD_RE.finditer(texto):
        indices.append((m.start(), int(m.group(1))))
    if not indices:
        return [(None, texto)]
    blocks = []
    for i, (start, unidad) in enumerate(indices):
        end = indices[i+1][0] if i+1 < len(indices) else len(texto)
        chunk = texto[start:end].strip()
        blocks.append((unidad, chunk))
    return blocks

# ======================= DATAFRAME =========================
def to_dataframe(items: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for it in items:
        unidad = coerce_unidad(it.get("unidad"))
        actividad = it.get("actividad", "").strip()
        fecha_txt = it.get("fecha_entrega", "").strip()
        fecha_iso = normalize_date_es(fecha_txt)
        descripcion = re.sub(r'\s+', ' ', it.get("descripcion", "").strip())
        valor_num = clean_valor_percent(it.get("valor_porcentaje", ""))

        rows.append({
            "Unidad": unidad,
            "N° Actividad": actividad,
            "Fecha de entrega (texto)": fecha_txt,
            "Fecha de entrega (ISO)": fecha_iso,
            "Descripción": descripcion,
            "Valor (%)": valor_num
        })
    df = pd.DataFrame(rows)
    if "Fecha de entrega (ISO)" in df.columns:
        df = df.sort_values(by=["Unidad", "Fecha de entrega (ISO)"], kind="stable", na_position="last")
    return df.reset_index(drop=True)

# ========================= MAIN ============================
def main():
    ap = argparse.ArgumentParser(description="Parsea actividades a DataFrame con LLM local (chunking por Unidad).")
    ap.add_argument("input_file", help="Archivo de texto con el contenido original.")
    ap.add_argument("--model", default="llama3.2:latest",  # <- por pedido tuyo
                    help='Modelo de Ollama (default: "llama3.2:latest").')
    ap.add_argument("--temperature", type=float, default=0.1, help="Temperatura para el LLM.")
    ap.add_argument("--out_csv", default="actividades.csv", help="Ruta de salida CSV.")
    ap.add_argument("--out_xlsx", default="actividades.xlsx", help="Ruta de salida XLSX (opcional).")
    args = ap.parse_args()

    try:
        texto = open(args.input_file, "r", encoding="utf-8").read()
    except FileNotFoundError:
        print(f"ERROR: no se pudo abrir '{args.input_file}'.", file=sys.stderr)
        sys.exit(1)

    bloques = split_by_unidad(texto)
    all_items: List[Dict[str, Any]] = []

    for unidad_detectada, bloque in bloques:
        # Le pasamos al LLM cada bloque para que no se pierda nada
        items = call_ollama_chunk(bloque, model=args.model, temperature=args.temperature)
        # Si el modelo no incluyó "unidad", la ponemos con la detectada
        for it in items:
            if it.get("unidad") in (None, "", "null"):
                it["unidad"] = unidad_detectada
        all_items.extend(items)

    df = to_dataframe(all_items)
    try:
        print(df.to_string(index=False))
    except Exception:
        print(df.head())

    df.to_csv(args.out_csv, index=False, encoding="utf-8")
    wrote_xlsx = False
    try:
        df.to_excel(args.out_xlsx, index=False)
        wrote_xlsx = True
    except Exception:
        pass

    msg = f"\nGuardado: {args.out_csv}"
    if wrote_xlsx:
        msg += f" y {args.out_xlsx}"
    print(msg)

if __name__ == "__main__":
    main()
