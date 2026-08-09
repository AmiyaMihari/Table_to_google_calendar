"""Conexión con Google Calendar: OAuth (flujo web) e inserción de eventos.

Notas sobre el flujo en Streamlit Cloud: cuando Google regresa al usuario a la
app, el navegador hace una recarga completa, así que `st.session_state` se
pierde. Por eso el `Flow` se reconstruye desde los secretos en cada ejecución y
los `state` pendientes viven en un diccionario a nivel de módulo (que sí
sobrevive entre sesiones dentro del mismo proceso).
"""

from __future__ import annotations

import json
import os
import secrets
import time as _time
from datetime import timedelta
from pathlib import Path

from .modelo import Evento

try:
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request

    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    DISPONIBLE = True
    ERROR_IMPORTACION = ""
except Exception as _e:  # pragma: no cover - sólo si faltan dependencias
    DISPONIBLE = False
    ERROR_IMPORTACION = str(_e)
    HttpError = Exception  # type: ignore
    RefreshError = Exception  # type: ignore

# `calendar` (y no sólo `calendar.events`) para poder crear un calendario nuevo.
ALCANCES = ["https://www.googleapis.com/auth/calendar"]

AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"

_VIGENCIA_ESTADO = 900  # segundos que aceptamos un `state` pendiente
_MAX_PENDIENTES = 200

# state -> (momento, code_verifier, datos_de_sesion).
#
# Guardar el verificador es obligatorio: la librería usa PKCE, manda su hash al
# pedir la autorización y Google exige el original al canjear el código. Como el
# `Flow` se reconstruye en la otra ejecución, si no lo conservamos aquí se pierde
# ("Missing code verifier").
#
# `datos_de_sesion` resuelve otro problema: al volver de Google el navegador
# recarga la página entera, Streamlit abre una sesión nueva y `session_state` se
# vacía. Este diccionario vive en el proceso, no en la sesión, así que es el
# único lugar donde el trabajo del usuario sobrevive el viaje de ida y vuelta.
_estados_pendientes: dict[str, tuple[float, str | None, dict | None]] = {}

# state -> (momento, credenciales, correo).
#
# El viaje a Google ocurre en una ventana emergente, que para Streamlit es una
# sesión distinta de la que la abrió: no comparten `session_state` ni forma
# alguna de hablarse desde el navegador (la emergente escapa del sandbox del
# iframe y queda en otro origen). Lo único que tienen en común es el proceso,
# así que la emergente deja aquí lo que consiguió y la pestaña original lo
# recoge sondeando por su `state`.
_credenciales_listas: dict[str, tuple[float, object, str]] = {}


class ErrorGoogle(Exception):
    """Fallo en la conexión con Google, con mensaje para el usuario."""


class SesionCaducada(ErrorGoogle):
    """El permiso de Google dejó de ser válido; hay que volver a conectarse."""


MENSAJE_CADUCADA = (
    "Tu permiso con Google dejó de ser válido (caduca al cabo de un rato, o lo "
    "retiraste desde tu cuenta). Pulsa «Desconectar» y vuelve a conectarte; no "
    "perderás los eventos que ya tienes."
)


def _llamar(que_hacia: str, funcion):
    """Ejecuta una llamada a la API convirtiendo los fallos en mensajes claros.

    El token de acceso caduca en una hora: sin esto, un usuario que deja la
    pestaña abierta se encuentra con que la app entera revienta.
    """
    try:
        return funcion()
    except RefreshError as e:
        raise SesionCaducada(MENSAJE_CADUCADA) from e
    except HttpError as e:
        raise ErrorGoogle(f"{que_hacia}: {e}") from e
    except ErrorGoogle:
        raise
    except Exception as e:
        raise ErrorGoogle(f"{que_hacia}: {type(e).__name__}: {e}") from e


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #

def leer_config(secretos, url_defecto: str = "") -> dict | None:
    """Extrae client_id / client_secret / redirect_uri de st.secrets.

    Si el secreto no trae `redirect_uri`, se usa la URL real de la app: así se
    evita el `redirect_uri_mismatch` por una diagonal de más o de menos.
    """
    try:
        cfg = secretos.get("google_oauth")
    except Exception:
        return None
    if not cfg:
        return None

    datos = {k: str(cfg.get(k, "")).strip() for k in ("client_id", "client_secret")}
    datos["redirect_uri"] = str(cfg.get("redirect_uri", "")).strip() or url_defecto.strip()
    if not all(datos.values()):
        return None
    return datos


# Dónde buscar el JSON que descarga Google Cloud, en desarrollo local.
# Todas estas carpetas están en .gitignore.
CARPETAS_LOCALES = ("env", "secrets", ".streamlit")


def leer_config_json(ruta, url_defecto: str = "") -> dict | None:
    """Lee el JSON de credenciales tal como lo descarga Google Cloud.

    El archivo trae los datos bajo la clave "web" (aplicación web) o
    "installed" (app de escritorio); se aceptan las dos.
    """
    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except Exception:
        return None

    cuerpo = datos.get("web") or datos.get("installed") or datos
    if not isinstance(cuerpo, dict):
        return None

    cliente = str(cuerpo.get("client_id", "")).strip()
    secreto = str(cuerpo.get("client_secret", "")).strip()
    if not cliente or not secreto:
        return None

    # La URL real de la app manda; el JSON sólo se usa si no la conocemos.
    uris = cuerpo.get("redirect_uris") or []
    destino = url_defecto.strip() or (str(uris[0]).strip() if uris else "")
    if not destino:
        return None

    return {"client_id": cliente, "client_secret": secreto, "redirect_uri": destino}


def buscar_config_local(base, url_defecto: str = "") -> dict | None:
    """Busca las credenciales en las carpetas locales típicas del proyecto."""
    raiz = Path(base)
    for carpeta in CARPETAS_LOCALES:
        for ruta in sorted(raiz.joinpath(carpeta).glob("*.json")):
            cfg = leer_config_json(ruta, url_defecto)
            if cfg:
                return cfg
    return None


def _client_config(cfg: dict) -> dict:
    return {
        "web": {
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": [cfg["redirect_uri"]],
        }
    }


def _preparar_entorno(cfg: dict) -> None:
    # Google a veces devuelve más alcances de los pedidos; sin esto, oauthlib truena.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    if cfg["redirect_uri"].startswith("http://localhost") or cfg["redirect_uri"].startswith("http://127.0.0.1"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def _flow(cfg: dict, state: str | None = None):
    if not DISPONIBLE:
        raise ErrorGoogle(
            "Faltan las librerías de Google. Instala: "
            "pip install google-auth google-auth-oauthlib google-api-python-client"
        )
    _preparar_entorno(cfg)
    flujo = Flow.from_client_config(_client_config(cfg), scopes=ALCANCES, state=state)
    flujo.redirect_uri = cfg["redirect_uri"]
    return flujo


# --------------------------------------------------------------------------- #
# Autorización
# --------------------------------------------------------------------------- #

def _purgar(registro: dict, ahora: float) -> None:
    """Tira lo caducado y lo más viejo si hay demasiado.

    Vale para los dos diccionarios de módulo porque ambos guardan el momento en
    la primera posición de la tupla. Sin esto crecerían sin fin: nadie recoge
    los intentos que el usuario abandona a medias.
    """
    for viejo in [s for s, datos in registro.items()
                  if ahora - datos[0] > _VIGENCIA_ESTADO]:
        registro.pop(viejo, None)
    while len(registro) > _MAX_PENDIENTES:
        registro.pop(min(registro, key=lambda s: registro[s][0]))


def depositar_credenciales(state: str, credenciales, correo: str = "") -> None:
    """Deja lo conseguido en la emergente para que lo recoja la pestaña original.

    El correo se guarda ya resuelto: quien recoge no debería tener que llamar a
    la API sólo para saber con qué cuenta se conectó.
    """
    ahora = _time.time()
    _purgar(_credenciales_listas, ahora)
    _credenciales_listas[state] = (ahora, credenciales, correo)


def recoger_credenciales(state: str):
    """Devuelve (credenciales, correo) de ese `state`, o None si no hay nada.

    Sacarlas es de un solo uso: una vez entregadas no tienen por qué seguir
    vivas en el proceso.
    """
    registro = _credenciales_listas.pop(state, None)
    if registro is None:
        return None
    return registro[1], registro[2]


def url_autorizacion(cfg: dict, datos_sesion: dict | None = None) -> tuple[str, str]:
    """URL a la que se manda al usuario para dar permiso, y su `state`.

    `datos_sesion` es lo que el usuario lleva hecho; se guarda aquí para poder
    devolvérselo cuando regrese, porque su sesión de Streamlit no sobrevive.

    El `state` se devuelve porque quien pinta el enlace lo necesita después: es
    la etiqueta con la que buscará en `_credenciales_listas` lo que la ventana
    emergente haya dejado.
    """
    ahora = _time.time()
    _purgar(_estados_pendientes, ahora)

    state = secrets.token_urlsafe(24)
    flujo = _flow(cfg, state=state)
    url, _ = flujo.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        # `select_account` obliga a Google a preguntar con qué cuenta entrar. Sin
        # esto usa la sesión que el navegador tenga por defecto, que en un equipo
        # con varias cuentas suele ser la del trabajo; si ésa pertenece a un
        # Workspace que bloquea apps sin verificar, Google responde 403 a secas.
        prompt="consent select_account",
    )
    # `authorization_url` genera el code_verifier; hay que conservarlo.
    _estados_pendientes[state] = (ahora, getattr(flujo, "code_verifier", None), datos_sesion)
    return url, state


def credenciales_desde_codigo(cfg: dict, codigo: str, state: str | None = None):
    """Canjea el código por credenciales. Devuelve (credenciales, datos_sesion)."""
    registro = _estados_pendientes.pop(state, None) if state is not None else None
    if state is not None and registro is None:
        raise ErrorGoogle(
            "La autorización expiró o no coincide. Vuelve a pulsar "
            "«Conectar con Google». (Si acabas de reiniciar la app, es normal: "
            "el intento anterior se perdió al reiniciarse.)"
        )

    flujo = _flow(cfg, state=state)
    if registro and registro[1]:
        flujo.code_verifier = registro[1]

    try:
        flujo.fetch_token(code=codigo)
    except Exception as e:
        raise ErrorGoogle(
            "No pude completar la conexión con Google. Si el enlace ya se usó una "
            "vez, vuelve a pulsar «Conectar con Google» para generar uno nuevo."
            f"\n\nDetalle: {type(e).__name__}: {e}"
        ) from e

    return flujo.credentials, (registro[2] if registro else None)


def refrescar(credenciales):
    if credenciales and credenciales.expired and credenciales.refresh_token:
        try:
            credenciales.refresh(Request())
        except Exception as e:
            raise SesionCaducada(MENSAJE_CADUCADA) from e
    return credenciales


def _servicio(credenciales):
    return build("calendar", "v3", credentials=refrescar(credenciales), cache_discovery=False)


def correo_usuario(credenciales) -> str:
    try:
        info = _servicio(credenciales).calendarList().get(calendarId="primary").execute()
        return info.get("id", "")
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Calendarios y eventos
# --------------------------------------------------------------------------- #

def listar_calendarios(credenciales) -> list[dict]:
    """Calendarios donde el usuario puede escribir."""
    respuesta = _llamar(
        "No pude leer tus calendarios",
        lambda: _servicio(credenciales).calendarList().list(maxResults=250).execute(),
    )

    salida = []
    for item in respuesta.get("items", []):
        if item.get("accessRole") in ("owner", "writer"):
            salida.append({
                "id": item["id"],
                "nombre": item.get("summary", item["id"]),
                "principal": bool(item.get("primary")),
            })
    salida.sort(key=lambda c: (not c["principal"], c["nombre"].lower()))
    return salida


def crear_calendario(credenciales, nombre: str, zona: str) -> str:
    creado = _llamar(
        f"No pude crear el calendario «{nombre}»",
        lambda: _servicio(credenciales).calendars().insert(
            body={"summary": nombre, "timeZone": zona}
        ).execute(),
    )
    return creado["id"]


def _recortar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    return texto[: limite - 3].rstrip() + "…"


def _cuerpo(ev: Evento, zona: str, duracion_horas: float, recordatorio_min: int | None) -> dict:
    if ev.todo_el_dia:
        inicio = {"date": ev.fecha_inicio.isoformat()}
        fin = {"date": (ev.fin_efectivo + timedelta(days=1)).isoformat()}
    else:
        inicio = {"dateTime": ev.inicio_dt().isoformat(), "timeZone": zona}
        fin = {"dateTime": ev.fin_dt(duracion_horas).isoformat(), "timeZone": zona}

    cuerpo = {
        "summary": ev.titulo,
        # La API rechaza el evento entero si la descripción pasa de 8192
        # caracteres. Los planes traen descripciones larguísimas (3.500 vistos),
        # así que se recorta antes: mejor un evento con la descripción a medias
        # que un evento que no se crea.
        "description": _recortar(ev.descripcion, 8192) or None,
        "location": ev.lugar or None,
        "start": inicio,
        "end": fin,
        "source": {"title": "Exportar Plan de Trabajo a Google Calendar", "url": "https://streamlit.io"},
    }
    if recordatorio_min:
        cuerpo["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": int(recordatorio_min)}],
        }
    return {k: v for k, v in cuerpo.items() if v is not None}


def _clave(titulo: str, fecha_iso: str) -> str:
    return f"{' '.join(titulo.lower().split())}|{fecha_iso[:10]}"


def eventos_existentes(credenciales, calendario_id: str, eventos: list[Evento]) -> set[str]:
    """Claves (título, día) ya presentes en el calendario, para no duplicar."""
    validos = [e for e in eventos if e.valido]
    if not validos:
        return set()

    inicio = min(e.fecha_inicio for e in validos) - timedelta(days=1)
    fin = max(e.fin_efectivo for e in validos) + timedelta(days=2)

    encontrados: set[str] = set()
    try:
        servicio = _servicio(credenciales)
        pagina = None
        while True:
            respuesta = servicio.events().list(
                calendarId=calendario_id,
                timeMin=f"{inicio.isoformat()}T00:00:00Z",
                timeMax=f"{fin.isoformat()}T00:00:00Z",
                singleEvents=True,
                maxResults=2500,
                pageToken=pagina,
            ).execute()
            for item in respuesta.get("items", []):
                arranque = item.get("start", {})
                fecha = arranque.get("date") or arranque.get("dateTime", "")
                if fecha:
                    encontrados.add(_clave(item.get("summary", ""), fecha))
            pagina = respuesta.get("nextPageToken")
            if not pagina:
                break
    except Exception:
        return set()  # es sólo para no duplicar: si falla, seguimos sin filtrar
    return encontrados


def insertar_eventos(
    credenciales,
    calendario_id: str,
    eventos: list[Evento],
    *,
    zona: str = "America/Mexico_City",
    duracion_horas: float = 2.0,
    recordatorio_min: int | None = None,
    evitar_duplicados: bool = True,
    progreso=None,
) -> dict:
    """Sube los eventos. Devuelve {creados, omitidos, errores: [str]}."""
    validos = [e for e in eventos if e.valido]
    ya_estan = eventos_existentes(credenciales, calendario_id, validos) if evitar_duplicados else set()

    servicio = _llamar("No pude conectar con Google", lambda: _servicio(credenciales))
    creados, omitidos, errores = 0, 0, []

    for i, ev in enumerate(validos, start=1):
        if progreso:
            progreso(i, len(validos), ev.titulo)

        if evitar_duplicados and _clave(ev.titulo, ev.fecha_inicio.isoformat()) in ya_estan:
            omitidos += 1
            continue

        for intento in range(3):
            try:
                servicio.events().insert(
                    calendarId=calendario_id,
                    body=_cuerpo(ev, zona, duracion_horas, recordatorio_min),
                ).execute()
                creados += 1
                break
            except HttpError as e:
                codigo = getattr(getattr(e, "resp", None), "status", 0)
                if codigo in (403, 429, 500, 503) and intento < 2:
                    _time.sleep(1.5 * (intento + 1))
                    continue
                errores.append(f"«{ev.titulo}»: {e}")
                break
            except Exception as e:
                errores.append(f"«{ev.titulo}»: {type(e).__name__}: {e}")
                break

    return {"creados": creados, "omitidos": omitidos, "errores": errores}
