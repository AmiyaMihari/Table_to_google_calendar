#!/usr/bin/env bash
# Crea (o repara) el entorno aislado del proyecto.
#
#   ./setup.sh          crea .venv e instala las dependencias
#   ./setup.sh --limpio borra .venv y lo vuelve a crear desde cero
#
# Después no hay que activar nada a mano: el hook de fish
# (~/.config/fish/conf.d/auto_venv.fish) y VS Code lo activan solos al entrar
# a la carpeta. Si usas bash/zsh: source .venv/bin/activate

set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

if [ "${1:-}" = "--limpio" ] && [ -d .venv ]; then
    echo "→ Borrando el .venv anterior…"
    rm -rf .venv
fi

if [ ! -d .venv ]; then
    echo "→ Creando .venv con $($PY --version)…"
    "$PY" -m venv .venv
fi

echo "→ Instalando dependencias…"
./.venv/bin/python -m pip install --quiet --upgrade pip
./.venv/bin/python -m pip install --quiet -r requirements.txt

echo
echo "Listo. Para arrancar la app:"
echo "    streamlit run app.py        (si el venv ya se activó solo)"
echo "    ./.venv/bin/streamlit run app.py   (si no)"
