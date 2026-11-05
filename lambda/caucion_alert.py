"""
Alerta de tasas de caución (IOL API -> Telegram), versión para AWS Lambda.

Solo usa la librería estándar de Python + boto3 (incluido en el runtime),
así no hay que empaquetar dependencias.

Secretos en SSM Parameter Store (SecureString), bajo el prefijo SSM_PREFIX:
  {prefijo}/iol_user, {prefijo}/iol_pass, {prefijo}/tg_token, {prefijo}/tg_chat

Variables de entorno (las pone Terraform):
  SSM_PREFIX   p.ej. /caucion-alert
  UMBRAL_TNA   % TNA a partir del cual avisa
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import boto3

BASE = "https://api.invertironline.com"
TOKEN_URL = f"{BASE}/token"
CAUCIONES_URL = (
    f"{BASE}/api/v2/Cotizaciones/cauciones/argentina/Todos"
    "?cotizacionInstrumentoModel.instrumento=cauciones"
    "&cotizacionInstrumentoModel.pais=argentina"
)

UMBRAL = float(os.environ.get("UMBRAL_TNA", "60"))
SSM_PREFIX = os.environ.get("SSM_PREFIX", "/caucion-alert")

# /tmp sobrevive entre invocaciones mientras el contenedor siga "caliente"
TMP = Path("/tmp")
TOKEN_FILE = TMP / "iol_token.json"
AVISOS_FILE = TMP / "avisos_hoy.json"

_secrets = None


def secrets():
    """Lee los secretos de SSM una sola vez por contenedor."""
    global _secrets
    if _secrets is None:
        ssm = boto3.client("ssm")
        resp = ssm.get_parameters_by_path(Path=SSM_PREFIX, WithDecryption=True)
        _secrets = {p["Name"].split("/")[-1]: p["Value"] for p in resp["Parameters"]}
    return _secrets


# ---------- HTTP mínimo con la librería estándar ----------

# Algunos firewalls bloquean el User-Agent por defecto de urllib ("Python-urllib/3.x")
USER_AGENT = "caucion-alert/1.0"


def _abrir(req):
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        cuerpo = e.read()[:500].decode(errors="replace")
        print(f"HTTP {e.code} en {req.full_url.split('?')[0]}: {cuerpo}")
        raise


def _post_form(url, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    })
    return _abrir(req)


def _get_json(url, token):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    })
    return _abrir(req)


# ---------- token (se reutiliza para no gastar llamadas) ----------

def _guardar_token(data):
    data["expira_ts"] = time.time() + int(data.get("expires_in", 900)) - 60
    TOKEN_FILE.write_text(json.dumps(data))
    return data


def _pedir_token():
    s = secrets()
    return _guardar_token(_post_form(TOKEN_URL, {
        "username": s["iol_user"],
        "password": s["iol_pass"],
        "grant_type": "password",
    }))


def obtener_token():
    if TOKEN_FILE.exists():
        data = json.loads(TOKEN_FILE.read_text())
        if time.time() < data.get("expira_ts", 0):
            return data["access_token"]
        if data.get("refresh_token"):
            try:
                return _guardar_token(_post_form(TOKEN_URL, {
                    "refresh_token": data["refresh_token"],
                    "grant_type": "refresh_token",
                }))["access_token"]
            except urllib.error.HTTPError:
                pass
    return _pedir_token()["access_token"]


# ---------- datos ----------

def obtener_cauciones():
    try:
        return _get_json(CAUCIONES_URL, obtener_token())
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        TOKEN_FILE.unlink(missing_ok=True)  # token vencido antes de tiempo
        return _get_json(CAUCIONES_URL, obtener_token())


def extraer_tasas(data):
    """Devuelve [(nombre, plazo, tasa)]. Ajustar si los campos difieren."""
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
    s = secrets()
    _post_form(f"https://api.telegram.org/bot{s['tg_token']}/sendMessage",
               {"chat_id": s["tg_chat"], "text": msg})


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


def lambda_handler(event, context):
    data = obtener_cauciones()
    if isinstance(event, dict) and event.get("debug"):
        # invocar con {"debug": true} para ver la respuesta cruda en los logs
        print(json.dumps(data, ensure_ascii=False)[:3000])

    avisos = []
    for nombre, plazo, tasa in extraer_tasas(data):
        if tasa >= UMBRAL and not ya_avisado(f"{nombre}-{plazo}"):
            msg = f"Caución {nombre} {plazo} a {tasa:.1f}% TNA (umbral {UMBRAL:.0f}%)"
            avisar(msg)
            avisos.append(msg)
    return {"avisos": avisos}