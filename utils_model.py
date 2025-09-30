# utils_model.py
# Utilidades: bandas, carga de modelo, envío de correo y diagnóstico SMTP.

import os, socket, ssl, smtplib
import joblib
from email.message import EmailMessage

# (opcional) carga .env local
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BANDAS_RIESGO = [
    ("Bajo",  0.00, 0.20),
    ("Medio", 0.20, 0.50),
    ("Alto",  0.50, 1.01),
]

def cargar_modelo(path: str = "modelo_logit_credito.joblib"):
    """
    Carga el modelo .joblib.
    Aplica un parche de compatibilidad si aparece el error:
    "Can't get attribute '_RemainderColsList' on sklearn.compose._column_transformer"
    que puede surgir al migrar entre versiones de scikit-learn.
    """
    try:
        return joblib.load(path)
    except AttributeError as e:
        msg = str(e)
        if "_RemainderColsList" in msg:
            # Parche de compatibilidad: inyectar símbolo esperado por pickles antiguos
            try:
                import sklearn.compose._column_transformer as ct  # type: ignore
                if not hasattr(ct, "_RemainderColsList"):
                    # Basta con mapearlo a list para que el unpickler resuelva el símbolo
                    setattr(ct, "_RemainderColsList", list)
            except Exception:
                # Si no pudimos importar/inyectar, relanzamos el error original
                raise
            # Reintentar la carga tras el parche
            return joblib.load(path)
        # Otros AttributeError: relanzar
        raise

def banda_riesgo(p: float) -> str:
    for nombre, lo, hi in BANDAS_RIESGO:
        if lo <= p < hi:
            return nombre
    return "N/A"

def _smtp_cfg():
    cfg = {
        "host": os.environ.get("SMTP_HOST"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER"),
        "pwd":  os.environ.get("SMTP_PASS"),
        "from": os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER"),
    }
    return cfg

def _mask(v):
    if not v: return ""
    s = str(v)
    return s if len(s) <= 4 else (s[:2] + "****" + s[-2:])

def validar_smtp_env():
    cfg = _smtp_cfg()
    faltan = [k for k,v in [
        ("SMTP_HOST", cfg["host"]), ("SMTP_PORT", cfg["port"]),
        ("SMTP_USER", cfg["user"]), ("SMTP_PASS", cfg["pwd"]),
        ("SMTP_FROM", cfg["from"])
    ] if not v]
    masked = {"host": _mask(cfg["host"]), "port": cfg["port"], "user": _mask(cfg["user"]),
              "pwd": _mask(cfg["pwd"]), "from": _mask(cfg["from"])}
    # Reglas de Gmail: FROM debe ser igual a USER (salvo alias verificado)
    warning_from = None
    if cfg["user"] and cfg["from"] and cfg["user"].lower() != cfg["from"].lower():
        warning_from = "En Gmail, SMTP_FROM debe ser igual a SMTP_USER (salvo alias verificado en la cuenta)."
    return (len(faltan)==0), faltan, masked, warning_from

def diagnostico_smtp_avanzado(timeout=10):
    """Retorna pasos de diagnóstico: DNS, socket, protocolo, auth."""
    cfg = _smtp_cfg()
    pasos = []

    if not all([cfg["host"], cfg["port"], cfg["user"], cfg["pwd"], cfg["from"]]):
        return {"ok": False, "pasos": [{"paso":"variables","ok":False,"detalle":"Faltan variables en .env"}]}

    # Paso 1: DNS
    try:
        ip = socket.gethostbyname(cfg["host"])
        pasos.append({"paso":"DNS", "ok": True, "detalle": f"{cfg['host']} → {ip}"})
    except Exception as e:
        return {"ok": False, "pasos": [{"paso":"DNS","ok":False,"detalle":str(e)}]}

    # Paso 2: Conexión de socket
    try:
        with socket.create_connection((cfg["host"], cfg["port"]), timeout=timeout) as _s:
            pasos.append({"paso":"Socket", "ok": True, "detalle": f"Conectó a {cfg['host']}:{cfg['port']}"})
    except Exception as e:
        return {"ok": False, "pasos": pasos + [{"paso":"Socket","ok":False,"detalle":str(e)}]}

    # Paso 3 y 4: Protocolo + AUTH
    try:
        if cfg["port"] == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=timeout) as server:
                server.login(cfg["user"], cfg["pwd"])
                pasos.append({"paso":"SSL(465)+AUTH", "ok": True, "detalle":"Login OK"})
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=timeout) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(cfg["user"], cfg["pwd"])
                pasos.append({"paso":"STARTTLS(587)+AUTH", "ok": True, "detalle":"Login OK"})
    except smtplib.SMTPAuthenticationError as e:
        pasos.append({"paso":"AUTH", "ok": False, "detalle": f"Autenticación falló: {e}"})
        return {"ok": False, "pasos": pasos}
    except smtplib.SMTPException as e:
        pasos.append({"paso":"SMTP", "ok": False, "detalle": f"Error SMTP: {e}"})
        return {"ok": False, "pasos": pasos}
    except Exception as e:
        pasos.append({"paso":"GENERAL", "ok": False, "detalle": f"Error: {e}"})
        return {"ok": False, "pasos": pasos}

    return {"ok": True, "pasos": pasos}

def enviar_email_simple(destinatario: str, asunto: str, cuerpo_texto: str, timeout: int = 15):
    """
    Envía correo; usa SSL si port==465, si no STARTTLS. Retorna (ok, msg).
    - Valida variables de entorno SMTP.
    - En Gmail, exige FROM == USER (salvo alias verificado).
    - Arma HTML seguro sin usar comillas triples.
    """
    cfg = _smtp_cfg()
    if not all([cfg["host"], cfg["port"], cfg["user"], cfg["pwd"], cfg["from"]]):
        return False, "Faltan variables de entorno SMTP."

    # Gmail: exigir FROM==USER para evitar rechazo silencioso
    if cfg["user"] and cfg["from"] and cfg["user"].lower() != cfg["from"].lower():
        return False, "Para Gmail, SMTP_FROM debe ser igual a SMTP_USER (salvo alias verificado)."

    # HTML seguro (sin f-string con backslashes ni triple quotes)
    cuerpo_html = (cuerpo_texto or "").replace("\n", "<br>")
    html = (
        "<html><body>"
        f"<p>{cuerpo_html}</p>"
        "</body></html>"
    )

    try:
        msg = EmailMessage()
        msg["Subject"] = asunto
        msg["From"] = cfg["from"]
        msg["To"] = destinatario
        msg.set_content(cuerpo_texto or "")
        msg.add_alternative(html, subtype="html")

        if cfg["port"] == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=timeout) as server:
                server.login(cfg["user"], cfg["pwd"])
                server.send_message(msg)
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=timeout) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(cfg["user"], cfg["pwd"])
                server.send_message(msg)
        return True, "OK"
    except smtplib.SMTPAuthenticationError as e:
        return False, f"Autenticación falló: {e}"
    except smtplib.SMTPException as e:
        return False, f"Error SMTP: {e}"
    except Exception as e:
        return False, f"Error general: {e}"
