# Despliegue en Streamlit Cloud

Guía para publicar la app. Son dos partes independientes:

| Parte | Cuesta | Qué habilita |
|---|---|---|
| **A. Publicar en Streamlit Cloud** | 15 min | Todo excepto el botón de envío directo |
| **B. Configurar OAuth de Google** | 30 min + trámite | El botón «🚀 Enviar a Google Calendar» |

**La parte B es opcional.** Sin ella la app funciona completa y el botón de envío
directo simplemente no aparece; los usuarios descargan el `.ics` e importan a
mano, que da el mismo resultado. Si tienes prisa, haz sólo la parte A.

---

## Parte A · Publicar en Streamlit Cloud

### 1. Sube el repositorio a GitHub

El repo debe ser **público** para usar el plan gratuito.

```bash
git add .
git commit -m "App Streamlit"
git push
```

Verifica que `.streamlit/secrets.toml` **no** esté versionado (ya está en
`.gitignore`).

### 2. Crea la app

1. Entra a [share.streamlit.io](https://share.streamlit.io) con tu cuenta de GitHub.
2. **Create app** → **Deploy a public app from GitHub**.
3. Llena:
   - **Repository**: `AmiyaMihari/Table_to_google_calendar`
   - **Branch**: `main`
   - **Main file path**: `app.py`
   - **App URL**: elige algo corto, p. ej. `tabla-a-google-calendar`
4. **Deploy**. Tarda unos minutos en instalar `requirements.txt`.

Al terminar tendrás una URL tipo
`https://tabla-a-google-calendar.streamlit.app` — **apúntala, la necesitas en la
parte B.**

### 3. Comparte la liga

Pásale a tus compañeros la URL y el [instructivo](INSTRUCTIVO.md).

> ⚠️ **Las apps gratuitas se duermen** tras unos días sin visitas. La primera
> persona que entre verá «*This app has gone to sleep*» y un botón para
> despertarla; tarda ~30 s. Avísales para que no crean que está rota.

### Actualizaciones

Cada `git push` a `main` redespliega automáticamente. Si cambias
`requirements.txt`, usa **Reboot app** desde el panel de Streamlit Cloud.

---

## Parte B · Envío directo a Google Calendar

### Cómo funciona (y por qué el trámite es inevitable)

Una duda razonable: *¿no hay forma de conectar con el calendario de cada persona
sin configurar nada?* La respuesta corta es que **el botón hace exactamente eso**,
pero alguien tiene que registrar la app ante Google una sola vez:

- **Tú, una vez:** creas el proyecto en Google Cloud y pegas dos claves. 30 min.
- **Cada compañero, siempre:** pulsa *Conectar con Google*, acepta, y los eventos
  se crean **en su propio calendario**. Ellos no configuran nada.

No existe una vía sin ese registro: Google no permite que una aplicación anónima
toque los datos de un usuario, y una **cuenta de servicio tampoco sirve** — no
puede escribir en calendarios personales de `@gmail.com` (eso requiere delegación
a nivel de dominio, que sólo existe en Google Workspace).

Si prefieres no hacer el trámite, las otras salidas de la app cubren el caso sin
permisos de ningún tipo: el **`.ics`** (computadora) y los **enlaces uno por uno**
(computadora o celular).

### El tope de 100 usuarios (léelo antes de repartir la liga)

El permiso de calendario es un **"scope sensible"** para Google. Una app que lo
pide y **no está verificada** tiene dos límites, incluso publicada en producción:

1. Los usuarios ven una pantalla de advertencia
   («*Google no ha verificado esta aplicación*») y deben pulsar
   **Configuración avanzada → Ir a (no seguro)** para continuar.
2. Un tope de **100 usuarios**, que es **de por vida del proyecto** y **no se
   puede reiniciar, ampliar ni solicitar**. No es una cuota: no hay formulario
   para pedir más. Cuenta usuarios distintos que han concedido el permiso.

**El tope no es un muro.** Si se llega a 100, nadie se queda fuera: los demás
usan el `.ics` o los enlaces uno por uno, que no tienen límite alguno. La app
está construida con esas tres salidas justamente por esto.

#### Si de verdad necesitas pasar de 100: verificación

Es el **único** camino, y es más accesible de lo que parece:

- **Es gratis.** El calendario es un scope *sensible*, no *restringido*. Los
  restringidos (Gmail, Drive) exigen una auditoría de seguridad externa anual que
  cuesta miles de dólares; **aquí no aplica**.
- **Tarda hasta 10 días hábiles**, no semanas.
- Al aprobarse, **desaparecen las dos cosas**: el tope y la pantalla roja.

Lo que Google pide:

| Requisito | Detalle |
|---|---|
| Dominio propio verificado | En Google Search Console. **`*.streamlit.app` no sirve**: no eres el dueño de ese dominio. |
| Página de inicio pública | En ese dominio, explicando qué hace la app. |
| Aviso de privacidad | En **el mismo dominio**, diciendo cómo se usan los datos de Google. |
| Video de demostración | En YouTube (no listado), mostrando el flujo de consentimiento con el nombre de la app y el `client_id` visibles en la barra de direcciones. |
| Justificación del scope | Por qué necesitas `auth/calendar`. |

El costo real es un dominio (~$150–250 MXN al año) y armar esas dos páginas
(GitHub Pages sirve y es gratis).

> ⚠️ **No abras proyectos nuevos para conseguir tandas de 100.** El tope existe
> precisamente contra eso y es de las cosas que hacen que Google suspenda
> proyectos.

👉 **Recomendación:** publica sin verificar, avisa en el instructivo que la
pantalla roja es normal, y vigila el contador en **Google Auth Platform →
Público**. Sólo si te acercas a 100 y el envío directo te importa, haz la
verificación.

### 1. Crea el proyecto y activa la API

1. Entra a [console.cloud.google.com](https://console.cloud.google.com).
2. Arriba, **Selector de proyecto → Proyecto nuevo**. Nómbralo p. ej.
   `tabla-a-calendar`.
3. **APIs y servicios → Biblioteca** → busca **Google Calendar API** → **Habilitar**.

### 2. Configura la pantalla de consentimiento

**APIs y servicios → Pantalla de consentimiento de OAuth**

- **Tipo de usuario**: `Externo` → **Crear**.
- **Nombre de la aplicación**: `Exportar Plan de Trabajo a Google Calendar`
- **Correo de asistencia** y **datos de contacto**: tu correo.
- **Permisos (scopes)** → **Agregar o quitar permisos** → busca y marca:
  ```
  https://www.googleapis.com/auth/calendar
  ```
- **Guardar y continuar** hasta terminar.

Después, en esa misma pantalla, elige una de las dos:

- **Modo `Prueba`**: agrega uno por uno los correos de tus compañeros en
  **Usuarios de prueba** (máx. 100). No ven advertencia tan agresiva, pero
  cualquier persona no listada queda fuera.
- **Modo `Producción`** (`Publicar aplicación`): entra cualquiera con cuenta de
  Google, pero todos ven la pantalla de «app no verificada».

Para repartir la liga en un grupo grande, **Producción** es lo práctico.

### 3. Crea las credenciales

**APIs y servicios → Credenciales → Crear credenciales → ID de cliente de OAuth**

- **Tipo de aplicación**: `Aplicación web`
- **Nombre**: `streamlit`
- **URI de redireccionamiento autorizados** → **Agregar URI**. Registra las dos
  formas de cada dirección, con y sin diagonal final: Google las compara
  carácter por carácter y basta una diferencia para que rechace la petición.
  ```
  https://tu-app.streamlit.app/
  https://tu-app.streamlit.app
  http://localhost:8501/
  http://localhost:8501
  ```

Google te muestra el **ID de cliente** y el **Secreto del cliente**. Cópialos.

### 4. Guarda los secretos en Streamlit Cloud

Panel de la app → **⋮ → Settings → Secrets** → pega:

```toml
[google_oauth]
client_id = "000000000000-xxxxxxxx.apps.googleusercontent.com"
client_secret = "GOCSPX-xxxxxxxxxxxxxxxx"
```

**Save.** La app se reinicia sola y aparece el botón **Conectar con Google**.

Si además quieres que **el PDF lo lea un modelo de OpenAI** (extrae las tablas
de cualquier formato de plan y resume las descripciones), añade en los mismos
*Secrets* una clave de la [API de OpenAI](https://platform.openai.com/):

```toml
[openai]
api_key = "sk-..."
# model = "gpt-5-mini"   # opcional; éste es el que se usa si no dices nada
```

**Quien pone la clave paga los tokens de todos los usuarios.** Cada lectura
cuesta dinero de verdad; antes de repartir la liga con esto activado, corre
`medir_ia.py` para saber cuánto te costaría por alumno. La app **no le enseña
ningún costo al estudiante** —no es él quien lo paga y no decide nada con esa
cifra—: el gasto se consulta en el panel de administración (aquí abajo). Sin
esta sección la app funciona igual con el lector clásico, que es gratuito. En
local, la clave puede ir en la variable de entorno `OPENAI_API_KEY` o en
`env/openai_secret.json` (`{"api_key": "sk-..."}`).

### Panel de administración (ver el gasto de la IA)

Al fondo de la barra lateral, debajo del crédito, puede aparecer un desplegable
**«Administración»** con lo que ha costado la lectura con IA: el gasto de la
sesión abierta y el acumulado de todas —lecturas, tokens y dólares, con
desglose por día y por archivo—.

**Sólo existe si le pones contraseña.** Sin ella no se dibuja nada: ni el
desplegable. En la nube, en los mismos *Secrets*:

```toml
[admin]
clave = "la-que-tú-elijas"
```

En local, en `env/admin_secret.json` (esa carpeta está en `.gitignore`):

```json
{"clave": "la-que-tú-elijas"}
```

Cada lectura pagada se apunta como una línea de `env/registro_ia.jsonl` —fecha,
archivo, modelo, tokens y costo—, que es de donde sale el acumulado. Dos
advertencias sobre ese archivo:

- **En Streamlit Cloud es efímero.** El disco de la app se rehace en cada
  redespliegue (y cada vez que la app despierta tras dormirse), así que el
  registro de la nube sirve para mirar los últimos días y nada más. El
  histórico de verdad es el de tu computadora.
- Si falla la escritura (disco lleno, permisos), la app **no se entera ni se
  detiene**: se pierde el apunte, no la lectura del PDF.

> **El `redirect_uri` no hace falta ponerlo**: la app usa su propia URL, que es
> justo lo que registraste en el paso 3. Sólo agrégalo como tercera línea si
> tienes la app detrás de un dominio propio o un proxy, y entonces debe coincidir
> **carácter por carácter** con el URI de Google (incluida la diagonal final) o
> Google responde `Error 400: redirect_uri_mismatch`.

---

## Desarrollo local

```bash
./setup.sh          # crea .venv e instala dependencias
streamlit run app.py
```

El `.venv` se activa solo al entrar a la carpeta (ver [README](../README.md)).

### Credenciales de Google en local

**No hace falta copiar nada a mano.** Cuando creas el cliente OAuth, Google te
ofrece **Descargar JSON**: guarda ese archivo dentro de `env/` y ya. La app lo
busca sola en `env/`, `secrets/` y `.streamlit/`, y acepta tanto el formato
`web` como el `installed`.

```
env/
└── secrets.json      ← el JSON tal cual lo descargaste
```

Las tres carpetas están en `.gitignore`, junto con `*client_secret*.json` y
`*credentials*.json`. **Nunca subas ese archivo**: si se filtra, Google revoca
las credenciales y cualquiera puede suplantar la app.

El orden de búsqueda es: primero los *Secrets* de Streamlit, y si no hay, el JSON
local. Por eso el mismo código sirve en tu compu y en la nube sin cambios.

Recuerda que `http://localhost:8501/` debe estar registrado como **URI de
redireccionamiento** en Google Cloud (no como *origen de JavaScript* — ése campo
no admite la diagonal final y déjalo vacío).

---

## Solución de problemas

| Síntoma | Causa y arreglo |
|---|---|
| `Error 400: redirect_uri_mismatch`, o un **403 seco** de Google («no tienes acceso a esta página») | El `redirect_uri` enviado no es idéntico al registrado. La trampa clásica es la **diagonal final**: `st.context.url` llega sin ella en Streamlit Cloud. La app ya la normaliza a `/`, pero registra ambas formas por si acaso. Para ver qué se envía de verdad: clic derecho en «Conectar con Google» → *Copiar dirección del enlace*, y mira el parámetro `redirect_uri`. |
| `Access blocked: app not verified` sin opción de continuar | La cuenta no está en *Usuarios de prueba* y la app sigue en modo `Prueba`. Agrégala o publica en `Producción`. |
| «La autorización expiró o no coincide» | El enlace de Google ya se usó o pasaron más de 15 min. Vuelve a pulsar *Conectar con Google*. |
| `ModuleNotFoundError` al desplegar | Falta la librería en `requirements.txt`, o Streamlit Cloud cacheó el entorno viejo: **Reboot app**. |
| Errores 403 al crear muchos eventos | Límite de escritura de Google Calendar. La app ya reintenta sola; si son cientos de eventos, súbelos en dos tandas. |

---

## Cómo está organizado el código

```
app.py                        Interfaz Streamlit (los 3 pasos)
tabla_calendar/
├── tablas.py                 Lee CSV/Excel/ODS, detecta la fila de encabezado
├── fechas.py                 Interpreta fechas y horas en español
├── deteccion.py              Adivina qué columna es cuál (nombre + contenido)
├── modelo.py                 Evento y armado de eventos desde la tabla
├── pdf.py                    Saca las tablas de un PDF midiendo su rejilla
├── ia.py                     Lee el PDF con un modelo de OpenAI; registro de gasto
├── exportar.py               Genera .ics y CSV de Google
└── google_calendar.py        OAuth e inserción vía API
docs/                         Este archivo y el instructivo
ejemplos/                     Archivos de prueba
legacy/                       La app de escritorio anterior (Tkinter + PyInstaller)
```

Cada módulo funciona sin Streamlit, así que puedes probarlos desde `python` o
reutilizarlos en un script.
