"""
Alerta de tasas de caución (IOL API -> Telegram)

Variables de entorno requeridas:
  IOL_USER, IOL_PASS          credenciales de IOL
  TG_TOKEN, TG_CHAT           bot de Telegram y chat id
Opcionales:
  UMBRAL_TNA   (default 60)   % TNA a partir del cual avisa
  INTERVALO    (default 60)   segundos entre chequeos en modo loop
  STATE_DIR    (default .)    carpeta donde guarda token y avisos del día

Uso:
  python caucion_alert.py --debug   # muestra la respuesta cruda para ver los campos
  python caucion_alert.py --once    # un solo chequeo (cron / Lambda)
  python caucion_alert.py           # loop de 11 a 17 h, días hábiles
"""

import json
import os
import sys
import time
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASE = "https://api.invertironline.com"
TOKEN_URL = f"{BASE}/token"
CAUCIONES_URL = (
    f"{BASE}/api/v2/Cotizaciones/cauciones/argentina/Todos"
    "?cotizacionInstrumentoModel.instrumento=cauciones"
    "&cotizacionInstrumentoModel.pais=argentina"
)

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
UMBRAL = float(os.environ.get("UMBRAL_TNA", "60"))
INTERVALO = int(os.environ.get("INTERVALO", "60"))
STATE_DIR = Path(os.environ.get("STATE_DIR", "."))
TOKEN_FILE = STATE_DIR / ".iol_token.json"
AVISOS_FILE = STATE_DIR / ".avisos_hoy.json"

HORA_INICIO, HORA_FIN = 11, 17


# ---------- token (se reutiliza para no gastar llamadas) ----------

def _guardar_token(data):
    data["expira_ts"] = time.time() + int(data.get("expires_in", 900)) - 60
    TOKEN_FILE.write_text(json.dumps(data))
    return data


def _pedir_token():
    r = requests.post(TOKEN_URL, data={
        "username": os.environ["IOL_USER"],
        "password": os.environ["IOL_PASS"],
        "grant_type": "password",
    }, timeout=15)
    r.raise_for_status()
    return _guardar_token(r.json())


def _refrescar_token(refresh_token):
    r = requests.post(TOKEN_URL, data={
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }, timeout=15)
    r.raise_for_status()
    return _guardar_token(r.json())


def obtener_token():
    if TOKEN_FILE.exists():
        data = json.loads(TOKEN_FILE.read_text())
        if time.time() < data.get("expira_ts", 0):
            return data["access_token"]
        if data.get("refresh_token"):
            try:
                return _refrescar_token(data["refresh_token"])["access_token"]
            except requests.HTTPError:
                pass
    return _pedir_token()["access_token"]


# ---------- datos ----------

def obtener_cauciones():
    headers = {"Authorization": f"Bearer {obtener_token()}",
               "Accept": "application/json"}
    r = requests.get(CAUCIONES_URL, headers=headers, timeout=15)
    if r.status_code == 401:  # token vencido antes de tiempo
        TOKEN_FILE.unlink(missing_ok=True)
        headers["Authorization"] = f"Bearer {obtener_token()}"
        r = requests.get(CAUCIONES_URL, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()


def extraer_tasas(data):
    """Devuelve [(nombre, plazo, tasa)]. Ajustar si los campos difieren (ver --debug)."""
    items = data.get("titulos", data) if isinstance(data, dict) else data
    tasas = []
    for it in items or []:
        tasa = it.get("ultimoPrecio") or it.get("tasa")
        if tasa is None:
            continue
        nombre = it.get("simbolo") or it.get("descripcion") or "caución"
        plazo = it.get("plazo") or it.get("plazoDias") or ""
        tasas.append((nombre, plazo, float(tasa)))
    return tasas


# ---------- avisos ----------

def avisar(msg):
    requests.post(
        f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
        data={"chat_id": os.environ["TG_CHAT"], "text": msg},
        timeout=15,
    )


def ya_avisado(clave):
    hoy = date.today().isoformat()
    estado = json.loads(AVISOS_FILE.read_text()) if AVISOS_FILE.exists() else {}
    if estado.get("dia") != hoy:
        estado = {"dia": hoy, "claves": []}
    if clave in estado["claves"]:
        return True
    estado["claves"].append(clave)
    AVISOS_FILE.write_text(json.dumps(estado))
    return False


def chequear():
    for nombre, plazo, tasa in extraer_tasas(obtener_cauciones()):
        if tasa >= UMBRAL and not ya_avisado(f"{nombre}-{plazo}"):
            avisar(f"Caución {nombre} {plazo} a {tasa:.1f}% TNA (umbral {UMBRAL:.0f}%)")


def en_horario():
    ahora = datetime.now(TZ)
    return ahora.weekday() < 5 and HORA_INICIO <= ahora.hour < HORA_FIN


# ---------- entrada ----------

def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if "--debug" in sys.argv:
        data = obtener_cauciones()
        print(json.dumps(data, indent=2, ensure_ascii=False)[:3000])
        print("\nTasas detectadas:", extraer_tasas(data))
        return
    if "--once" in sys.argv:
        if en_horario():
            chequear()
        return
    while True:
        if en_horario():
            try:
                chequear()
            except Exception as e:  # no cortar el loop por un error puntual
                print(f"{datetime.now(TZ):%H:%M:%S} error: {e}", file=sys.stderr)
        time.sleep(INTERVALO)


def lambda_handler(event, context):
    """Para AWS Lambda: configurar la variable de entorno STATE_DIR=/tmp."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if en_horario():
        chequear()


if __name__ == "__main__":
    main()
