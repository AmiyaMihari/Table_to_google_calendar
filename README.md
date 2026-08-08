# 📅 Exportar Plan de Trabajo a Google Calendar

Convierte la tabla de actividades y asesorías de un plan de trabajo de SUAyED en
eventos de Google Calendar. Aplicación web: **no hay que instalar nada**.

> **Para usarla:** lee el **[instructivo](docs/INSTRUCTIVO.md)**.
> **Para publicarla:** lee la **[guía de despliegue](docs/DESPLIEGUE.md)**.

---

## Qué hace

Eliges arriba qué vas a importar — **📝 Actividades y entregas** o
**🎥 Videoconferencias y asesorías** — y la app pide sólo los campos de ese tipo.
Los eventos se acumulan, así que puedes hacer las dos tablas y exportarlas juntas.

Subes el plan en CSV o Excel y la app:

- **Encuentra sola dónde empieza la tabla**, aunque arriba haya logos, títulos o
  filas en blanco.
- **Adivina qué columna es cuál** mirando el nombre del encabezado *y* el
  contenido (una columna cuyos valores parecen fechas es la columna de fechas,
  aunque se llame «Unnamed: 3»).
- **Entiende las fechas como las escribe la gente**: `21/08/2025`, `19- feb-25`,
  `21 de agosto de 2025`, `del 21 al 25 de agosto`, fechas reales de Excel y
  hasta números de serie.
- **Distingue entregas de asesorías**: las entregas quedan como eventos de todo
  el día y las asesorías con su horario (`16:00 a 18:00`, `de 4 a 6 pm`).
- **Rellena las celdas combinadas** de la columna *Unidad*.
- Te deja **revisar y corregir todo** en una tabla editable antes de exportar.
- Junta varias hojas (actividades + asesorías) en una sola lista.

Y luego, a elegir según lo que tengas a la mano:

| Salida | Permisos | Clics | Celular |
|---|---|---|---|
| **🚀 Enviar directo** a Google Calendar — puede crear un calendario dedicado a la materia y evita duplicados | uno, una vez | 1 para todo | ✅ |
| **📅 Descargar `.ics`** — con recordatorios y UID estable, así que reimportar actualiza en vez de duplicar | ninguno | 3 para todo | ❌ |
| **🔗 Enlaces uno por uno** — abren Google Calendar ya llenado | ninguno | 1 por evento | ✅ |
| **📄 CSV** en el formato de Google, como último recurso | ninguno | 3 para todo | ❌ |

## Correr en local

```bash
./setup.sh          # crea .venv e instala dependencias
streamlit run app.py
```

Se abre en <http://localhost:8501>.

El `.venv` se activa **solo** al entrar a la carpeta, en dos frentes:

- **VS Code** — por [`.vscode/settings.json`](.vscode/settings.json), en cada
  terminal nueva y para ejecutar/depurar.
- **fish** — si tienes el hook `~/.config/fish/conf.d/auto_venv.fish`, que busca
  `.venv` en la carpeta actual o en sus padres. En bash/zsh: `source .venv/bin/activate`.
- **direnv** (opcional) — si lo instalas, un `.envrc` con
  `source .venv/bin/activate` hace lo mismo en cualquier shell.

Python: local corre en 3.14; el código es compatible desde 3.9, y en Streamlit
Cloud conviene elegir **3.13** (lo más nuevo que soporta). El envío directo a
Google requiere configurar `secrets.toml`; sin eso todo lo demás funciona igual.

## Estructura

```
app.py                  Interfaz (los 4 pasos)
tabla_calendar/         Lógica, sin dependencia de Streamlit
  tablas.py             Lectura de CSV/Excel/ODS + detección de encabezado
  fechas.py             Fechas y horas en español
  deteccion.py          Mapeo automático de columnas
  modelo.py             Evento y construcción desde la tabla
  exportar.py           .ics y CSV de Google
  google_calendar.py    OAuth e inserción vía API
docs/                   Instructivo y guía de despliegue
ejemplos/               Archivos de prueba
legacy/                 Versión anterior de escritorio (Tkinter + .exe)
```

## Versión anterior

En [legacy/](legacy/) queda la app de escritorio original en Tkinter, empaquetada
con PyInstaller, junto con el experimento de extracción del PDF con un LLM local
vía Ollama (`parse_plan_light.py`). Se conserva como respaldo; el desarrollo
continúa en la versión web.

---

Hecho para SUAyED · [@AmiyaMihari](https://github.com/AmiyaMihari)
