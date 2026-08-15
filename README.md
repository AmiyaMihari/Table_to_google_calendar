# 📅 Exportar Plan de Trabajo a Google Calendar

Convierte la tabla de actividades y asesorías de un plan de trabajo de SUAyED en
eventos de Google Calendar. Aplicación web: **no hay que instalar nada**.

> **Para usarla:** lee el **[instructivo](docs/INSTRUCTIVO.md)**.
> **Para publicarla:** lee la **[guía de despliegue](docs/DESPLIEGUE.md)**.

---

## Qué hace

Tres pasos: **1** subir el archivo y marcar qué tablas trae, **2** revisar y
ajustar, **3** exportar.

Lo único que decides es qué pasar al calendario — **Actividades y entregas** o
**Videoconferencias y asesorías** —. En un PDF ni eso: cada tabla que encuentra
ya viene con su tipo y basta con marcarla. En CSV y Excel se pregunta **ya con el
archivo delante**, en el paso 1 y con la respuesta puesta. Cada tipo pide sólo
sus campos, y las dos cosas pueden ir a la vez: se revisan en pestañas separadas
y se exportan juntas.

Subes el plan **en PDF, CSV o Excel** y la app:

- **Lee el PDF tal cual te lo dieron**: busca dentro sus tablas, junta las que
  cruzan varias páginas y te enseña las que encontró («Actividades — 14 filas,
  páginas 6 a 24») **con una casilla cada una, para que marques las que
  quieras**: actividades y videoconferencias en un solo viaje. El tipo lo pone
  el propio nombre de la tabla, así que no hay nada más que elegir.
  Si quien publica
  la app configuró una clave de OpenAI, el PDF lo lee **un modelo GPT** —aguanta
  formatos de plan que el lector clásico no conoce y **resume la descripción de
  cada actividad** en un par de frases—; sin clave trabaja el lector clásico de
  siempre, gratuito y sin enviar nada a ningún servicio. Si el plan trae
  una tabla de videoconferencias por grupo, te las ofrece todas **con el nombre
  del asesor**, que es lo que de verdad te dice cuál es la tuya. Vienen marcadas
  las actividades; **las videoconferencias no**, para que las elijas tú.
- **Sabe si tu CSV o tu Excel son entregas o sesiones**: si la tabla trae
  horarios de verdad propone videoconferencias, y si no, actividades. Se corrige
  con un clic.
- **Agrupa las tablas del PDF por tipo**: primero las actividades y, debajo,
  bajo *«Elegir el grupo que corresponda»*, las videoconferencias de cada grupo,
  para que marques la de tu asesor y ninguna más.
- **Saca sola el nombre de la materia** del propio plan y lo pone en los
  eventos; si no acierta, lo cambias en un campo.
- **Encuentra sola dónde empieza la tabla**, aunque arriba haya logos, títulos o
  filas en blanco.
- **Adivina qué columna es cuál** mirando el nombre del encabezado *y* el
  contenido (una columna cuyos valores parecen fechas es la columna de fechas,
  aunque se llame «Unnamed: 3»).
- **Entiende las fechas como las escribe la gente**: `21/08/2025`, `19- feb-25`,
  `21 de agosto de 2025`, `del 21 al 25 de agosto` —que queda como un evento de
  varios días—, fechas reales de Excel y hasta números de serie.
- **Distingue entregas de asesorías**: las entregas quedan como eventos de todo
  el día y las asesorías con su horario (`16:00 a 18:00`, `de 4 a 6 pm`).
- **Rellena las celdas combinadas** de la columna *Unidad*.
- Te deja **revisar y corregir todo** en una tabla editable antes de exportar, en
  el mismo paso donde se ajusta qué columna es cuál.
- **«Agregar otro calendario»** limpia todo para la siguiente materia sin
  desconectarte de Google: es el camino para pasar dos planes seguidos.

Y luego, a elegir según lo que tengas a la mano:

| Salida | Permisos | Clics | Celular |
|---|---|---|---|
| **Enviar directo** a Google Calendar — puede crear un calendario dedicado a la materia y evita duplicados | uno, una vez | 1 para todo | sí |
| **Descargar `.ics`** — con recordatorios y UID estable, así que reimportar actualiza en vez de duplicar | ninguno | 3 para todo | no |
| **Enlaces uno por uno** — abren Google Calendar ya llenado | ninguno | 1 por evento | sí |
| **CSV** en el formato de Google, como último recurso | ninguno | 3 para todo | no |

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
app.py                  Interfaz (los 3 pasos)
tabla_calendar/         Lógica, sin dependencia de Streamlit
  tablas.py             Lectura de CSV/Excel/ODS + detección de encabezado
  pdf.py                Reconstrucción de las tablas del PDF
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
