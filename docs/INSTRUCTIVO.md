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
- entregas que ocupan varios días («del 21 al 25 de agosto»),
- columnas extra que no sirven (valor en puntos, ponderación, etc.).

---

## Paso 1 · Sube tu archivo y marca qué pasar al calendario

Arrastra el archivo al recuadro, o pulsa para buscarlo.

Formatos aceptados: `.pdf`, `.xlsx`, `.xlsm`, `.xls`, `.ods`, `.csv`.

En cuanto lo lee, cada tabla queda clasificada en uno de estos dos tipos. Si
subiste un PDF, la app lo decide sola; si subiste CSV o Excel te lo pregunta,
y tampoco tienes que pensarla mucho: **viene contestada** y casi siempre acierta.

| Opción | Para qué | Cómo quedan en el calendario |
|---|---|---|
| **Actividades y entregas** | La tabla de tareas con fecha límite | Eventos de **todo el día** |
| **Videoconferencias y asesorías** | La tabla de sesiones con horario | Eventos **con hora de inicio y fin** |

- **Si subiste el PDF**, verás **«Tablas encontradas en el PDF»** y las que
  encontró dentro, **cada una con su casilla** («Actividades — 14 filas, páginas
  6 a 24», «Videoconferencias · grupo 8396 · *nombre de tu asesora*»). El
  nombre de cada una ya te dice de qué es, así que no hay nada más que elegir:
  **marca todas las que quieras** y se pasan al calendario juntas, sin subir el
  archivo dos veces.
  - Las **actividades** vienen marcadas de entrada: son las mismas para todos
    los grupos y es a lo que viene casi todo el mundo.
  - Las **videoconferencias** vienen **desmarcadas**, siempre. A las sesiones en
    vivo va quien va, así que las marcas tú. Si tu plan trae una tabla por
    grupo, **elige la de tu asesor**, que aparece con su nombre al lado del
    número de grupo.
  - Si la app te avisa de que los **años** de tu plan no cuadran, repásalos
    antes de exportar: alguna tabla puede haber quedado con el año equivocado.
  - El **horario de dudas de tu asesor** («martes y jueves de 14:00 a 16:00») no
    sale como tabla y no se pasa al calendario: no son sesiones a las que haya
    que ir, sino las horas en que puedes escribirle.
- **Si subiste CSV o Excel**, sale **«Tipo de tabla»** con la respuesta puesta:
  si la tabla trae una columna de horarios propone *Videoconferencias*, y si no,
  *Actividades*. Si se equivoca, la corriges con un clic. En un Excel con varias
  hojas, elige primero la hoja —cada una puede ser de un tipo distinto— y la
  propuesta se recalcula.

Verás un mensaje verde: *«Tabla leída: 12 filas y 4 columnas»*, o *«Se leyeron 18
filas en total»* si marcaste varias. Si el número de filas se ve raro, lo
arreglas en el paso 2.

> 💡 **¿Tienes las dos cosas en archivos distintos?** Sube el primero y, al final
> del paso 1, pulsa **«Añadir otro archivo»**: te dice cuántos eventos llevas,
> los guarda y te deja el recuadro libre para el siguiente. **Al final se
> exportan todos juntos.** (Si las dos tablas venían en el mismo PDF, esto no
> hace falta: márcalas juntas y ya.)

## Paso 2 · Revisa y ajusta

Aquí va todo lo que se puede corregir de cada tabla: qué es cada columna y, justo
debajo, los eventos ya armados. Si marcaste varias tablas, aparece **una pestaña
por tabla** («Actividades», «Videoconferencias · grupo 8396…»); lo que sigue vale
para cada una por separado.

### Las columnas

Arriba hay un desplegable cerrado que dice lo que la app detectó sola:
*«Se detectaron 6 de 6 columnas. Abrir para elegirlas manualmente.»* Casi nunca
hay que abrirlo. Se abre solo cuando no encontró la columna de fechas, que es lo
único imprescindible.

Dentro sólo salen los campos que importan para el tipo de esa tabla:

- **Actividades** → Fecha de entrega, Nombre de la actividad, Unidad, Descripción.
  Cuatro y ya: no hay nada opcional que llenar.
- **Videoconferencias** → Fecha de la sesión, Nombre de la sesión, Hora de inicio,
  Hora de fin. Debajo, los marcados **«(opcional)»** —descripción, liga de Zoom,
  número de sesión—, que la mayoría de los planes no traen: si dicen
  *«— ninguna —»*, está bien así.

### Los eventos

Debajo aparece la tabla con los eventos ya armados —**numerados 1, 2, 3…**, así
que ahí se ve cuántos son— y los contadores de **filas leídas**, **eventos
listos** y los que **necesitan revisión**.

Todo aquí es **editable**. Puedes:

- corregir un título o una fecha que no se entendió (`«por confirmar»`, por ejemplo),
- desmarcar la casilla *Incluir* de las filas que no quieres,
- ajustar horarios.

Si alguna fila tiene algo que revisar, aparece una columna **«Revisar»** que dice
qué le pasa. Si no aparece, es que está todo en orden.

**No hay que confirmar nada.** Todo lo que ves aquí ya cuenta para el paso 3;
puedes bajar directamente.

## Paso 3 · Mándalos a tu calendario

Arriba verás el resumen —*«12 eventos en total»*, y de qué tabla salió cada
uno—. La lista completa está en el paso 2, que es donde se edita; aquí sólo se
elige el camino:

| | Permisos | Clics | Celular |
|---|---|---|---|
| **Enviar directo** | Das permiso una vez | 1 para todo | ✅ |
| **Archivo `.ics`** | Ninguno | 3 para todo | ❌ sólo computadora |
| **Enlaces uno por uno** | Ninguno | 1 por evento | ✅ |

### Opción A — Enviar directo (lo más rápido)

1. En la barra de la izquierda, pulsa **Conectar con Google**. Se abre una
   **ventana pequeña**: acepta el permiso ahí y se cierra sola. Tu pestaña de
   siempre queda conectada, con el archivo y la tabla tal como los dejaste — no
   la cierres ni la recargues mientras tanto.

   > Si tu navegador bloquea las ventanas emergentes, no pasa nada: debajo del
   > botón hay un enlace **«¿No se abrió la ventana? Conectar en otra pestaña»**
   > que hace lo mismo por el camino de siempre.

2. En **«Calendario destino»**, elige a dónde van. Te recomendamos **Crear un
   calendario nuevo para esta materia**: así, al terminar el semestre, lo ocultas
   o lo borras completo de un clic sin tocar tus otros eventos.
3. Deja marcado **«No duplicar eventos que ya existan»**.
4. Pulsa **Crear 12 eventos en Google Calendar**. Listo. 🎉

### Opción B — Descargar el archivo `.ics`

Funciona siempre y no requiere dar ningún permiso.

1. Pestaña **Descargar archivo .ics** → **Descargar .ics**.
2. Entra a [calendar.google.com](https://calendar.google.com) **desde una
   computadora** (esto no se puede hacer desde la app del celular).
3. **Configuración** → **Importar y exportar** → **Importar**.
4. Elige el archivo, selecciona el calendario destino y pulsa **Importar**.

> ✅ Si más adelante te corrigen una fecha, vuelve a generar el `.ics` y a
> importarlo: Google **actualiza** los eventos en vez de duplicarlos.

### Opción C — Enlaces uno por uno (la que sirve en el celular)

Google **no deja importar archivos desde el celular**, sólo desde computadora.
Si estás en el teléfono y no quieres dar permisos, ésta es tu opción:

1. Pestaña **Enlaces (sirve en celular)**.
2. Pulsa **Añadir** en el evento que quieras: se abre Google Calendar con todo
   ya llenado (título, fecha, horario, descripción).
3. Pulsa **Guardar**. Repite con el siguiente.

Es un evento a la vez, así que para 15 actividades conviene más la Opción A o B
desde una computadora. Para las 4 o 5 videoconferencias del semestre, va perfecto.

### Opción D — CSV

Sólo si las anteriores fallan. Google interpreta las fechas del CSV según el
idioma de tu cuenta, así que si los eventos caen en el día equivocado, cambia el
formato de fecha en esa misma pestaña y vuelve a importar.

---

## Problemas comunes

**«No pude abrir el archivo»**
Suele ser un `.xls` viejo o un archivo protegido con contraseña. Ábrelo en Excel
y guárdalo como `.xlsx`.

**La tabla se leyó con encabezados raros («Columna 1», «Unnamed…»)**
Abre el desplegable de columnas del paso 2 (*«Se detectaron … columnas»*): al
final ajustas en qué fila están los títulos.

**Las fechas cayeron en el día equivocado**
`03/04/2025` puede ser 3 de abril o 4 de marzo. En la barra lateral →
**Ajustes avanzados** → elige *Día/Mes/Año*. También puedes corregir cualquier
fecha a mano en la tabla del paso 2.

**Mi plan no pone el año** («21 de agosto»)
En **Ajustes avanzados**, escribe el año correcto en *«Año para fechas escritas
sin año»*.

**Los títulos salen muy largos o muy cortos**
Escribe el nombre de la materia en la barra lateral, y si quieres cambia el
*Título de las actividades* o el *Título de las videoconferencias* en **Ajustes
avanzados** (cada tipo de evento tiene el suyo). Puedes usar `{materia}`,
`{unidad}` y `{titulo}`.

**Una tabla del PDF quedó del tipo equivocado**
El tipo de las tablas de un PDF lo pone la app al reconocerlas, y lo dice el
nombre con el que aparece cada casilla. Si una no es lo que dice ser,
**desmárcala en el paso 1**: lo más probable es que esa tabla no fuera del plan.
Si el archivo era CSV o Excel, el tipo sí se cambia a mano, con el selector
**«Tipo de tabla»** del paso 1; todo el paso 2 se acomoda solo.

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
