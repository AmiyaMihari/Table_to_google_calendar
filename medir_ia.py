"""Mide cuánto costaría leer los PDF de planes de trabajo con un modelo de OpenAI.

Recorre los PDF de `testing_files/` (los `.csv` de esa carpeta se ignoran) y
produce un informe de tokens y costo en USD, para decidir si conviene escalar
la lectura por IA a más usuarios. Dos formas de correrlo:

    .venv/bin/python medir_ia.py --simular            # sin clave: sólo estima
    .venv/bin/python medir_ia.py                       # con clave: mide de verdad
       [--modelo gpt-5-mini] [--pdf <subcadena>] [--limite N]

En modo real necesita una clave de OpenAI (variable `OPENAI_API_KEY` o
`env/openai_secret.json`) y hace una llamada por PDF a `tabla_calendar.ia`. En
modo `--simular` no llama a la API ni importa ese módulo —puede correr aunque
`tabla_calendar/ia.py` no exista todavía o falte el SDK de OpenAI—: usa
`pdfplumber` directamente para contar páginas y caracteres, y estima tokens
con una fórmula burda.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from tabla_calendar import pdf

RAIZ = Path(__file__).parent
CARPETA_PDF = RAIZ / "testing_files"

# El mismo valor que trae `tabla_calendar.ia.MODELO_POR_DEFECTO`. Se repite
# aquí (en vez de importar `ia`) para que el modo --simular y la ayuda de
# argparse no dependan de que ese módulo exista.
MODELO_POR_DEFECTO = "gpt-5-mini"

# Copia local de `tabla_calendar.ia.PRECIOS` (USD por millón de tokens: entrada,
# entrada cacheada, salida). La copia canónica vive en tabla_calendar/ia.py;
# ésta es sólo para el modo --simular, que por contrato no debe importar ese
# módulo. El precio de caché no entra en la estimación: la primera lectura de
# un PDF no tiene nada cacheado.
PRECIOS_SIMULADOS: dict[str, tuple[float, float, float]] = {
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
}

_LARGO_NOMBRE = 40

# Fórmula burda para el modo --simular: unos 3.5 caracteres por token de
# entrada más un colchón fijo de instrucciones, y una salida que crece con el
# número de filas que el lector clásico encontró (cada fila es, a grandes
# rasgos, un evento más en el JSON de salida).
_CARACTERES_POR_TOKEN = 3.5
_TOKENS_INSTRUCCIONES = 900
_TOKENS_SALIDA_BASE = 350
_TOKENS_SALIDA_POR_FILA = 55


@dataclass
class Medicion:
    """Tokens y costo de un PDF, vengan de una llamada real o de una estimación."""

    nombre: str
    paginas: int
    entrada: int
    salida: int
    costo: float | None


def _normalizar(texto: str) -> str:
    """Minúsculas y sin acentos, para que --pdf compare sin distinguirlos."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_acentos = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return sin_acentos.lower()


def _recortar(nombre: str, largo: int = _LARGO_NOMBRE) -> str:
    if len(nombre) <= largo:
        return nombre
    return nombre[: largo - 1] + "…"


def _fmt_usd(valor: float) -> str:
    return f"${valor:,.4f}"


def _fmt_int(valor: int) -> str:
    return f"{valor:,}"


def _listar_pdfs(filtro: str | None, limite: int | None) -> list[Path]:
    rutas = sorted(CARPETA_PDF.glob("*.pdf"))
    if filtro:
        buscado = _normalizar(filtro)
        rutas = [r for r in rutas if buscado in _normalizar(r.stem)]
    if limite is not None:
        rutas = rutas[:limite]
    return rutas


def _contar_filas_por_tipo(candidatas: list) -> tuple[int, int]:
    """(filas de actividades, filas de videoconferencias) de una lista de Candidata."""
    actividades = sum(len(c.df) for c in candidatas if c.tipo == pdf.TIPO_ACTIVIDADES)
    video = sum(len(c.df) for c in candidatas if c.tipo == pdf.TIPO_VIDEOCONFERENCIAS)
    return actividades, video


def _contar_paginas_y_caracteres(datos: bytes) -> tuple[int, int]:
    """Páginas y caracteres de texto de un PDF, leyendo con pdfplumber directamente.

    No usa `pdf.texto_completo` a propósito: el modo --simular tiene que poder
    correr aunque el resto del módulo de IA todavía no exista.
    """
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(datos)) as documento:
        paginas = len(documento.pages)
        caracteres = sum(len(p.extract_text() or "") for p in documento.pages)
    return paginas, caracteres


def _resumen_final(mediciones: list[Medicion], precios: dict[str, tuple[float, float, float]]) -> None:
    """Totales, costo medio, comparación entre modelos y proyección de uso."""
    if not mediciones:
        print("No hay ninguna medición que resumir.")
        return

    total_entrada = sum(m.entrada for m in mediciones)
    total_salida = sum(m.salida for m in mediciones)
    con_costo = [m.costo for m in mediciones if m.costo is not None]
    total_costo = sum(con_costo)
    costo_medio = total_costo / len(con_costo) if con_costo else None

    print("\n=== Resumen ===")
    print(f"PDF procesados:              {len(mediciones)}")
    print(f"Tokens de entrada, total:    {_fmt_int(total_entrada)}")
    print(f"Tokens de salida, total:     {_fmt_int(total_salida)}")
    if con_costo:
        print(f"Costo total:                 {_fmt_usd(total_costo)}")
        print(
            f"Costo medio por PDF:         {_fmt_usd(costo_medio)}"
            f"  (sobre {len(con_costo)} PDF con costo calculado)"
        )
    else:
        print("Costo total:                 sin datos (ningún modelo con precio conocido)")

    print(
        "\nEl mismo volumen de tokens bajo cada modelo (orientativo: cada modelo "
        "puede tokenizar y razonar distinto, así que las otras cifras son aproximadas):"
    )
    for modelo, (precio_entrada, _, precio_salida) in precios.items():
        costo_modelo = (
            total_entrada / 1_000_000 * precio_entrada
            + total_salida / 1_000_000 * precio_salida
        )
        print(f"  {modelo:<20} {_fmt_usd(costo_modelo)}")

    if costo_medio is not None:
        print("\nProyección si N alumnos suben 1 PDF cada uno (costo medio × N):")
        for n in (100, 500):
            print(f"  {n:>4} alumnos:  {_fmt_usd(costo_medio * n)}")


def modo_simular(pdfs: list[Path], modelo: str) -> int:
    precios = PRECIOS_SIMULADOS
    if modelo not in precios:
        print(
            f"Aviso: «{modelo}» no está en la tabla de precios simulada; "
            f"uso {MODELO_POR_DEFECTO} para el costo."
        )
        modelo = MODELO_POR_DEFECTO
    precio_entrada, _, precio_salida = precios[modelo]

    print(f"Modo --simular: sin clave de API, estimación burda con el modelo {modelo}.\n")

    mediciones: list[Medicion] = []
    for ruta in pdfs:
        nombre = _recortar(ruta.stem)
        datos = ruta.read_bytes()

        try:
            paginas, caracteres = _contar_paginas_y_caracteres(datos)
        except Exception as e:
            print(f"{nombre}: no se pudo leer con pdfplumber — {type(e).__name__}: {e}")
            continue

        try:
            candidatas = pdf.extraer(datos)
        except pdf.ErrorDePDF as e:
            print(f"{nombre}: {e}")
            continue

        actividades, video = _contar_filas_por_tipo(candidatas)
        filas = actividades + video
        entrada = round(caracteres / _CARACTERES_POR_TOKEN + _TOKENS_INSTRUCCIONES)
        salida = round(_TOKENS_SALIDA_BASE + _TOKENS_SALIDA_POR_FILA * filas)
        costo = entrada / 1_000_000 * precio_entrada + salida / 1_000_000 * precio_salida
        mediciones.append(Medicion(nombre=ruta.stem, paginas=paginas, entrada=entrada, salida=salida, costo=costo))

        print(
            f"{nombre:<{_LARGO_NOMBRE}}  páginas: {paginas:>2}  filas (act·video): {actividades}·{video}  "
            f"tokens (estimación burda) entrada/salida: {_fmt_int(entrada)}/{_fmt_int(salida)}  "
            f"costo: {_fmt_usd(costo)}"
        )

    _resumen_final(mediciones, precios)
    return 0


def modo_real(pdfs: list[Path], modelo: str | None) -> int:
    from tabla_calendar import ia

    config = ia.buscar_clave_local(RAIZ)
    if not config or not config.get("api_key"):
        print(
            "No encontré ninguna clave de OpenAI.\n\n"
            "Ponla en la variable de entorno OPENAI_API_KEY, o crea el archivo\n"
            'env/openai_secret.json con el contenido: {"api_key": "tu-clave-aquí"}'
        )
        return 1
    clave = config["api_key"]
    modelo = modelo or config.get("model") or ia.MODELO_POR_DEFECTO

    print(f"Modo real: midiendo con el modelo {modelo}.\n")

    mediciones: list[Medicion] = []
    for ruta in pdfs:
        nombre = _recortar(ruta.stem)
        datos = ruta.read_bytes()

        try:
            texto = pdf.texto_completo(datos)
        except pdf.ErrorDePDF as e:
            print(f"{nombre}: {e}")
            continue
        paginas = len(re.findall(r"=== Página \d+ ===", texto))

        try:
            resultado = ia.extraer(texto, clave, modelo)
        except ia.ErrorDeIA as e:
            print(f"{nombre}: error de la IA — {e}")
            continue

        try:
            candidatas_clasico = pdf.extraer(datos)
        except pdf.ErrorDePDF as e:
            print(f"{nombre}: error del lector clásico — {e}")
            continue

        act_ia, video_ia = _contar_filas_por_tipo(resultado.candidatas)
        act_clasico, video_clasico = _contar_filas_por_tipo(candidatas_clasico)

        uso = resultado.uso
        mediciones.append(
            Medicion(nombre=ruta.stem, paginas=paginas, entrada=uso.entrada, salida=uso.salida, costo=uso.costo_usd)
        )

        print(
            f"{nombre:<{_LARGO_NOMBRE}}  páginas: {paginas:>2}  "
            f"filas (act·video) IA vs clásico: {act_ia}·{video_ia} | {act_clasico}·{video_clasico}"
        )
        print(f"    {uso.resumen()}")

    _resumen_final(mediciones, ia.PRECIOS)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mide cuánto costaría, en tokens y dólares, leer los PDF de "
            "testing_files/ con un modelo de OpenAI."
        ),
    )
    parser.add_argument(
        "--simular",
        action="store_true",
        help="No llama a la API de OpenAI: sólo estima el costo con pdfplumber y el lector clásico.",
    )
    parser.add_argument(
        "--modelo",
        default=None,
        help=f"Modelo de OpenAI a usar (por defecto {MODELO_POR_DEFECTO}).",
    )
    parser.add_argument(
        "--pdf",
        default=None,
        metavar="SUBCADENA",
        help="Filtra los PDF de testing_files/ cuyo nombre contenga esta subcadena.",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        metavar="N",
        help="Usa sólo los primeros N PDF de la lista (después de aplicar --pdf).",
    )
    args = parser.parse_args()

    pdfs = _listar_pdfs(args.pdf, args.limite)
    if not pdfs:
        print("No encontré ningún PDF en testing_files/ con ese filtro.")
        return 1

    if args.simular:
        return modo_simular(pdfs, args.modelo or MODELO_POR_DEFECTO)
    return modo_real(pdfs, args.modelo)


if __name__ == "__main__":
    sys.exit(main())
