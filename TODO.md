# Pendientes

Estado al 8 de agosto de 2026. La app está desplegada en
<https://suayed-autocalendar.streamlit.app/> y funciona de la tabla en adelante.

---

## 1. Leer el PDF directamente — **hecho**, a falta de probarlo en real

Implementado en la rama `extract_pdf`: `tabla_calendar/pdf.py` más el paso de
elección en `app.py`. Se sube el PDF tal cual, la app enseña las tablas que
encontró y el usuario elige; de ahí en adelante el flujo es el de siempre.

Resultado sobre los cinco planes de `testing_files/`, contrastado con lo que
dice cada PDF de sí mismo:

| Plan | Actividades | Cómo se comprobó | Videoconferencias |
|---|---|---|---|
| Estructura de Datos | 18 | conteo a mano de la rejilla | 4 (1 grupo) |
| Matemáticas Financieras | 14 | igual al CSV hecho a mano | 4 |
| Principios y técnicas | 12 | sus porcentajes cuadran con su propio total | 4 + 4 (2 grupos) |
| Programación Neurolingüística | 8 | «Ponderación total de las actividades» | 2 |
| Recursos Humanos | 12 | «Suma total de Actividades» | 4 + 4 (2 grupos) |

Las cinco tablas de actividades salen al 100 % de confianza (todas las filas con
una fecha que se entiende).

> **Ojo:** esa columna es cómo verifiqué *yo* el resultado, leyendo el total que
> cada PDF declara. **El código no usa los porcentajes para nada** y no da por
> sentado ningún total: cuánto suman las actividades lo decide cada profesor.
> Lo único que mira `_PIES` es la redacción de la fila de cierre, no su cifra.

### Lo que falta

- **Probarlo con gente de verdad.** Es lo único que queda de este punto.
- **Cuatro celdas sueltas** salen sucias porque la rejilla del propio PDF las
  parte mal: en Matemáticas Financieras una descripción arranca con un «1»
  suelto y un nombre de actividad queda a medias; en Principios (grupo 8196) una
  sesión pierde el horario y a otra se le cuela el apellido del asesor. Se
  corrigen en el paso 3 y no se arrastran a lo demás.
- **Un plan de una familia nueva** seguramente falle. Para eso está la señal de
  confianza y el aviso de «no pude leer esto»; el flujo manual sigue en pie.

### Decisión: sin LLM en el motor

Lo que varía entre planes es la **geometría de la tabla**, no el idioma. Las 22
cadenas reales de fecha y hora de los cinco PDFs de `testing_files/` las acierta
`fechas.py` sin modelo alguno («28 febrero», «20 al 25 de octubre 2025»,
«25 febrero – 18:00 – 20:00 horas», «20 de agosto de 2025 a las 20:00 a 22:00 h»).
Eso es justo lo que se le pediría a un LLM, y ya está resuelto gratis.

Además, un extractor determinista que se equivoca lo hace **de forma visible**, y
el paso 3 (tabla editable) ya es la red de seguridad. Un LLM se equivoca
inventando filas plausibles, que en esta app es mucho peor.

El LLM queda como **salida de emergencia**, no como motor, y se decide cuando
aparezca un plan que de verdad falle. Para eso el extractor va en su propio
módulo (`tabla_calendar/pdf.py`), de modo que un `pdf_llm.py` se enchufe después
sin tocar nada más. Lo de «qué API y quién paga» sigue sin decidir, pero ya no
bloquea.

### Son dos familias de formato, no una

|  | **Familia A** (Mat. Financieras, PNL) | **Familia B** (Est. Datos, RRHH, Principios) |
|---|---|---|
| Actividades | `UNIDAD, ACTIVIDAD, DESCRIPCIÓN, FECHA DE ENTREGA, PONDERACIÓN` | `Unidad, N° Actividad, Fecha de entrega, Descripción, Valor` |
| Encabezado | partido en dos líneas, repetido en cada página | una sola vez; las páginas siguientes no lo repiten |
| Filas | descripción partida en cientos de filas de continuación | una fila por actividad |
| Videoconf. | `SESIÓN, FECHA / HORA, TEMA A TRATAR` | `GRUPO, VIDEOCONFERENCIA, FECHA Y HORA, ASESOR(A)` |

Los cinco PDFs son de texto; ninguno escaneado.

### Estado de los prototipos

Dos tácticas probadas, ninguna cubre las dos familias sola:

- **Compactar la rejilla de `pdfplumber`** (quitar celdas vacías de cada fila):
  14/14 actividades en Matemáticas Financieras, y `detectar_columnas` mapeó la
  tabla sin ayuda. No sirve para la familia B.
- **Bandas por coordenadas de las palabras** (ignorar la rejilla y agrupar por
  posición en x): Recursos Humanos 12/12 — verificado contra el «Suma total de
  Actividades 60%» del propio PDF —, Estructura de Datos 22 filas donde deben
  ser 18, Principios 13, familia A 0 porque no detecta el encabezado partido.

Entre las dos está casi todo el camino. Cálculo: 300–400 líneas con pruebas
contra los cinco PDFs.

### Cómo quedó resuelto cada obstáculo

1. **Encabezado partido en dos líneas** (`FECHA DE` / `ENTREGA`):
   `_unir_encabezado` pega la segunda fila cuando trae pocas celdas, cortas y
   sin fecha.
2. **Filas de continuación**: una fila abre registro sólo si trae ≥2 celdas y
   una de ellas es una fecha **corta**; el resto se pega a la descripción.
3. **La tabla entre páginas**: con encabezado repetido se agrupa por firma
   (familia A); sin él, `_continua_la_tabla` la engancha si la página es
   consecutiva y trae filas con fecha (familia B).
4. **Rejilla desplazada**: se compacta la fila **y el encabezado**, y la fecha
   ancla la fila — lo que va antes y después conserva su orden alrededor.
5. **Señal de confianza**: `Candidata.confianza` es la proporción de filas con
   fecha entendible; si no llega al 100 % se avisa en pantalla.

### Decisiones tomadas (8 de agosto de 2026)

- **Las actividades son las que diga el PDF**, aunque no cuadren con un CSV
  hecho a mano.
- **Sólo actividades y videoconferencias en vivo.** La tabla de videos grabados
  (`SESIÓN | TEMA A TRATAR | OBSERVACIONES`, «Verla antes de…») **se ignora**.
- **Un grupo por asesor:** en la familia B hay una tabla de videoconferencias
  por grupo (Recursos Humanos trae 8396 y 8397, con horarios distintos). La app
  **enseña las dos y el usuario elige**.
- **Las fechas de exámenes no se incluyen** (`PARCIAL | … | FECHA DE
  APLICACIÓN`): son iguales para todas las materias y duran varios días.
- **PDF escaneado: fuera de alcance.** Sólo detectarlo (si una página no suelta
  texto, es una imagen) y decirlo claro: «este PDF es una imagen escaneada, no
  puedo leer su tabla». Ahí sí haría falta OCR, y ninguno de los planes reales
  lo necesita.

### Cómo quedó en la interfaz

Se sube el PDF y la app enseña las tablas **agrupadas** (no las 43 sueltas:
quedan dos o tres candidatas reales, tipo «📝 Actividades — 14 filas, págs.
6–24»). Al elegir una de videoconferencias, el tipo de importación cambia solo.

Cuando hay una tabla por grupo, la etiqueta lleva **el nombre del asesor** junto
al número: nadie se sabe su número de grupo de memoria, pero a su asesor sí lo
reconoce. Y el **nombre de la materia** se saca de la portada y se rellena solo.

Como un PDF trae **las dos tablas a la vez**, «Incluir también…» del paso 4 ya
no obliga a volver a subir nada: salta a la otra tabla del mismo archivo. Eso sí,
tiene que cambiar de tabla — dejar la misma seleccionada duplicaría sus eventos
al exportar.

`pdfplumber` ya está en `requirements.txt`. Arrastra `pdfminer.six`, ~15 MB.

El experimento anterior con Ollama local está en `legacy/parse_plan_light.py`.
Se descartó porque obligaba a los compañeros a instalar cosas, pero los prompts
y la normalización de fechas siguen siendo aprovechables.

---

## 2. Verificación de Google (sólo si se acerca a 100 usuarios)

La app está publicada sin verificar: tope de **100 usuarios de por vida del
proyecto**, que no se puede reiniciar ni ampliar. No es un muro — quien quede
fuera usa el `.ics` o los enlaces uno por uno, que no tienen límite.

Para levantarlo hay que verificar, y es gratis (el calendario es un permiso
*sensible*, no *restringido*: no aplica la auditoría de seguridad de pago).
Tarda hasta 10 días hábiles y pide dominio propio verificado, con página de
inicio y aviso de privacidad alojados ahí, más un video de demostración.
`*.streamlit.app` no sirve porque el dominio no es tuyo.

Vigilar el contador en **Google Auth Platform → Público**.

---

## 3. Menores

- **Segunda tabla de actividades.** El botón «Incluir también…» siempre cambia
  al otro tipo. Quien tenga dos tablas de actividades (dos materias) tiene que
  volver a cambiar el tipo a mano. Poco frecuente; ver si molesta.
- **Aviso de app dormida.** Las apps gratuitas se duermen sin visitas y la
  primera persona ve «This app has gone to sleep». Está avisado en el
  instructivo, pero conviene repetirlo al compartir la liga.
- **Repartir el instructivo.** [docs/INSTRUCTIVO.md](docs/INSTRUCTIVO.md) va
  junto con el enlace, sobre todo por la pantalla de «app no verificada».
