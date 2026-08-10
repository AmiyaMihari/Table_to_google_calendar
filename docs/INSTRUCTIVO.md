# 📅 Cómo pasar tu plan de trabajo a Google Calendar

Guía para compañeras y compañeros de SUAyED. **No necesitas instalar nada**: todo
se hace desde el navegador, igual en computadora que en celular.

👉 **Entra aquí: [tabla-a-google-calendar.streamlit.app](https://tabla-a-google-calendar.streamlit.app)**

> Reemplaza esa liga por la de tu despliegue si publicaste tu propia copia.

---

## Antes de empezar: te basta con el plan de trabajo

Sube el **PDF del plan tal como te lo dieron**: la app busca dentro sus tablas
—las actividades y las videoconferencias— y te enseña las que encontró.

¿Prefieres pasarle la tabla ya suelta, o tu plan trae un formato que no reconoce?
También acepta **CSV y Excel**:

1. Abre el PDF y **selecciona la tabla completa** (incluyendo la fila de títulos:
   *Unidad*, *Actividad*, *Fecha de entrega*, *Descripción*…).
2. Cópiala con `Ctrl + C`.
3. Abre **Excel** o **Google Sheets** y pega con `Ctrl + V`.
4. Guarda el archivo como `.xlsx` (Excel) o descárgalo como `.csv` (Sheets).

**No te preocupes si queda imperfecto.** La app sabe manejar:

- filas de logotipo o de título arriba de la tabla,
- la columna *Unidad* con celdas combinadas (huecos debajo del número),
- fechas en cualquier formato: `21/08/2025`, `19- feb-25`, `21 de agosto de 2025`,
- columnas extra que no sirven (valor en puntos, ponderación, etc.).

---

## Paso 1 · Sube tu archivo y di qué es

Arrastra el archivo al recuadro, o pulsa para buscarlo.

Formatos aceptados: `.pdf`, `.xlsx`, `.xlsm`, `.xls`, `.ods`, `.csv`.

En cuanto lo lee, te pregunta **«¿Qué quieres pasar al calendario?»**. Ésta es la
decisión más importante, porque cambia todo lo que la app te pide después — pero
no tienes que pensarla: **viene contestada** y casi siempre acierta.

| Opción | Para qué | Cómo quedan en el calendario |
|---|---|---|
| 📝 **Actividades y entregas** | La tabla de tareas con fecha límite | Eventos de **todo el día** |
| 🎥 **Videoconferencias y asesorías** | La tabla de sesiones con horario | Eventos **con hora de inicio y fin** |

- **Si subiste el PDF**, la pregunta son las tablas que encontró dentro
  («📝 Actividades — 14 filas, págs. 6–24», «🎥 Videoconferencias · grupo 8396 ·
  *nombre de tu asesora*»). Eliges una y con eso queda dicho todo. Si tu plan
  trae una tabla de videoconferencias por grupo, elige la de tu asesor.
- **Si subiste CSV o Excel**, la app mira tu tabla: si trae una columna de
  horarios propone *Videoconferencias*, y si no, *Actividades*. Si se equivoca,
  la corriges con un clic. En un Excel con varias hojas, elige primero la hoja
  —cada una puede ser de un tipo distinto— y la propuesta se recalcula.

Verás un mensaje verde: *«Tabla leída: 12 filas y 4 columnas»*. Si el número de
filas se ve raro, lo arreglas en el paso 2.

> 💡 **¿Tienes las dos cosas?** Es lo normal, y está previsto: empieza por las
> actividades y, cuando llegues al final, pulsa **«➕ Incluir también
> videoconferencias»**. La app guarda lo que llevas y te lleva a la otra tabla:
> si subiste el PDF, ya la tiene dentro y salta sola; si no, sólo te pide que
> subas la otra. **Al final se exportan todas juntas.**

## Paso 2 · Revisa qué es cada columna

La app **ya detectó sola** qué columna es cuál, y sólo te muestra los campos que
importan para el tipo que elegiste:

- **Actividades** → Fecha de entrega, Nombre de la actividad, Unidad, Descripción.
- **Videoconferencias** → Fecha de la sesión, Nombre de la sesión, Hora de inicio,
  Hora de fin.

Lo demás (fecha final, liga de Zoom, etc.) está guardado en **«Columnas
opcionales»** para no estorbar.

Casi siempre acierta. Sólo revisa que la **Fecha** apunte a la columna correcta;
si algo está mal, cámbialo en el menú desplegable.

## Paso 3 · Revisa y corrige

Aparece la tabla con los eventos ya armados y tres contadores:
**filas leídas**, **eventos listos** y **necesitan revisión**.

Todo aquí es **editable**. Puedes:

- corregir un título o una fecha que no se entendió (`«por confirmar»`, por ejemplo),
- desmarcar la casilla ✓ de las filas que no quieres,
- ajustar horarios.

**No hay que confirmar nada.** Todo lo que ves aquí ya cuenta para el paso 4;
puedes bajar directamente.

## Paso 4 · Mándalos a tu calendario

Tienes varios caminos; elige según lo que tengas a la mano:

| | Permisos | Clics | Celular |
|---|---|---|---|
| 🚀 **Enviar directo** | Das permiso una vez | 1 para todo | ✅ |
| 📅 **Archivo `.ics`** | Ninguno | 3 para todo | ❌ sólo computadora |
| 🔗 **Enlaces uno por uno** | Ninguno | 1 por evento | ✅ |

### 🚀 Opción A — Enviar directo (lo más rápido)

1. En la barra de la izquierda, pulsa **Conectar con Google**. Se abre una
   **ventana pequeña**: acepta el permiso ahí y se cierra sola. Tu pestaña de
   siempre queda conectada, con el archivo y la tabla tal como los dejaste — no
   la cierres ni la recargues mientras tanto.

   > Si tu navegador bloquea las ventanas emergentes, no pasa nada: debajo del
   > botón hay un enlace **«¿No se abrió la ventana? Conéctate en otra pestaña»**
   > que hace lo mismo por el camino de siempre.

2. Elige a qué calendario van. Te recomendamos **➕ Crear un calendario nuevo
   para esta materia**: así, al terminar el semestre, lo ocultas o lo borras
   completo de un clic sin tocar tus otros eventos.
3. Deja marcado **«No duplicar eventos que ya existan»**.
4. Pulsa **🚀 Crear eventos**. Listo. 🎉

### 📅 Opción B — Descargar el archivo `.ics`

Funciona siempre y no requiere dar ningún permiso.

1. Pestaña **Descargar archivo .ics** → **📥 Descargar .ics**.
2. Entra a [calendar.google.com](https://calendar.google.com) **desde una
   computadora** (esto no se puede hacer desde la app del celular).
3. ⚙️ **Configuración** → **Importar y exportar** → **Importar**.
4. Elige el archivo, selecciona el calendario destino y pulsa **Importar**.

> ✅ Si más adelante te corrigen una fecha, vuelve a generar el `.ics` y a
> importarlo: Google **actualiza** los eventos en vez de duplicarlos.

### 🔗 Opción C — Enlaces uno por uno (la que sirve en el celular)

Google **no deja importar archivos desde el celular**, sólo desde computadora.
Si estás en el teléfono y no quieres dar permisos, ésta es tu opción:

1. Pestaña **Enlaces (sirve en celular)**.
2. Pulsa **➕ Añadir** en el evento que quieras: se abre Google Calendar con todo
   ya llenado (título, fecha, horario, descripción).
3. Pulsa **Guardar**. Repite con el siguiente.

Es un evento a la vez, así que para 15 actividades conviene más la Opción A o B
desde una computadora. Para las 4 o 5 videoconferencias del semestre, va perfecto.

### 📄 Opción D — CSV

Sólo si las anteriores fallan. Google interpreta las fechas del CSV según el
idioma de tu cuenta, así que si los eventos caen en el día equivocado, cambia el
formato de fecha en esa misma pestaña y vuelve a importar.

---

## Problemas comunes

**«No pude abrir el archivo»**
Suele ser un `.xls` viejo o un archivo protegido con contraseña. Ábrelo en Excel
y guárdalo como `.xlsx`.

**La tabla se leyó con encabezados raros («Columna 1», «Unnamed…»)**
Abre **«Configuración manual»** en el paso 2: ahí ajustas en qué fila están los
títulos de las columnas.

**Las fechas cayeron en el día equivocado**
`03/04/2025` puede ser 3 de abril o 4 de marzo. En la barra lateral →
**Ajustes avanzados** → elige *Día/Mes/Año*. También puedes corregir cualquier
fecha a mano en la tabla del paso 3.

**Mi plan no pone el año** («21 de agosto»)
En **Ajustes avanzados**, escribe el año correcto en *«Año para fechas escritas
sin año»*.

**Los títulos salen muy largos o muy cortos**
Escribe el nombre de la materia en la barra lateral, y si quieres cambia la
*Plantilla del título* en Ajustes avanzados. Puedes usar `{materia}`, `{unidad}`
y `{titulo}`.

**Me equivoqué y ya importé todo**
Si creaste un calendario nuevo para la materia, bórralo completo desde Google
Calendar (⚙️ Configuración → el calendario → *Quitar calendario*) y vuelve a
empezar.

---

## ¿Es seguro?

- Tu archivo **no se guarda** en ningún lado: se procesa en memoria mientras usas
  la página y desaparece al cerrarla.
- El permiso de Google se usa **sólo** para crear los eventos que tú confirmes.
  Puedes retirarlo cuando quieras desde
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
- Si prefieres no dar ningún permiso, usa la **Opción B** (archivo `.ics`): hace
  exactamente lo mismo.

---

¿Algo no funcionó o tienes una idea? Escríbeme:
[github.com/AmiyaMihari](https://github.com/AmiyaMihari)
