"""
main.py - Punto de entrada principal del Bot Inmobiliario ORESNA
Servidor FastAPI con webhook de WhatsApp Cloud API

Endpoints:
  GET  /          → Health check
  GET  /webhook   → Verificación Meta (solo primera vez)
  POST /webhook   → Recepción de mensajes entrantes
  GET  /simulator → Simulador visual de WhatsApp (solo desarrollo)
  POST /simulate  → Enviar mensaje al bot sin WhatsApp real (solo desarrollo)
  GET  /messages/{phone} → Obtener respuestas pendientes del bot (simulador)
  GET  /leads     → Ver leads capturados (solo desarrollo)
  POST /reset/{phone} → Reiniciar sesión de un usuario (solo desarrollo)
"""
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from app.core.config import settings
from app.bot.conversation import gestor
from app.bot.rag_engine import motor_rag
from app.integrations.whatsapp_client import WhatsAppClient, SimulatorWhatsAppClient

# ── Configuración de logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Ciclo de vida de la app ──────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialización al arrancar el servidor"""
    logger.info("=" * 55)
    logger.info("Iniciando ORESNA WhatsApp Bot...")
    logger.info("=" * 55)

    # Cargar catálogo de propiedades y construir índice RAG
    motor_rag.cargar_propiedades(settings.CATALOG_PATH)
    logger.info(f"Catalogo cargado: {motor_rag.total()} propiedades disponibles")

    # Verificar configuración
    if not settings.WHATSAPP_TOKEN or settings.WHATSAPP_TOKEN in ("", "tu_token_de_meta_aqui"):
        logger.warning("WHATSAPP_TOKEN no configurado -> Modo SIMULACION activo")
        logger.info("Simulador disponible en: http://localhost:8000/simulator")
    else:
        logger.info(f"WhatsApp conectado | Phone ID: {settings.PHONE_NUMBER_ID}")

    if not settings.GROQ_API_KEY or settings.GROQ_API_KEY.startswith("PENDIENTE"):
        logger.warning("GROQ_API_KEY no configurada. Las respuestas de IA fallarán.")
    else:
        logger.info("Groq AI configurado correctamente")

    if not settings.BOSS_PHONE:
        logger.warning("BOSS_PHONE no configurado (alertas al jefe desactivadas)")
    else:
        logger.info(f"Asesor configurado: +{settings.BOSS_PHONE}")

    logger.info(f"Verify Token: {settings.VERIFY_TOKEN}")
    logger.info("Bot listo para recibir mensajes")
    logger.info("=" * 55)

    yield

    logger.info("Bot detenido")


# ── Aplicación FastAPI ───────────────────────────────────────────────────────
app = FastAPI(
    title="ORESNA WhatsApp Bot",
    description="Bot inmobiliario con IA (RAG + Gemini) para WhatsApp Cloud API",
    version="1.2.0",
    lifespan=lifespan,
)

wsp = WhatsAppClient()


# ── Modelos ──────────────────────────────────────────────────────────────────

class SimulateRequest(BaseModel):
    phone: str
    mensaje: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/", tags=["Status"])
async def health():
    """Health check - muestra el estado del bot"""
    from app.integrations.whatsapp_client import MODO_SIMULACION
    return {
        "status": "activo",
        "modo": "simulacion" if MODO_SIMULACION else "produccion",
        "propiedades_en_catalogo": motor_rag.total(),
        "sesiones_activas": len(gestor.sesiones),
        "version": "1.2.0",
        "simulador": "http://localhost:8000/simulator" if MODO_SIMULACION else None,
    }


@app.get("/webhook", tags=["WhatsApp"])
async def verificar_webhook(
    hub_mode: str = None,
    hub_challenge: str = None,
    hub_verify_token: str = None,
):
    """
    Verificación del webhook por Meta (solo se llama una vez al configurar).
    Meta envía una petición GET con hub.verify_token para confirmar que el
    servidor es tuyo. Devuelve hub.challenge si el token es correcto.
    """
    logger.info(
        f"Verificacion webhook - mode: {hub_mode}, token: {hub_verify_token}"
    )

    if hub_mode == "subscribe" and hub_verify_token == settings.VERIFY_TOKEN:
        logger.info("Webhook verificado correctamente por Meta")
        return Response(content=hub_challenge, media_type="text/plain")

    logger.warning(
        f"Verificacion fallida. "
        f"Token recibido: '{hub_verify_token}' | "
        f"Token esperado: '{settings.VERIFY_TOKEN}'"
    )
    return Response(status_code=403, content="Token incorrecto")


@app.post("/webhook", tags=["WhatsApp"])
async def recibir_mensaje(request: Request):
    """
    Endpoint principal: recibe todos los mensajes entrantes de WhatsApp.
    Meta envía aquí los mensajes de los usuarios en tiempo real.
    """
    try:
        body = await request.json()
        logger.debug(f"Webhook raw: {json.dumps(body, ensure_ascii=False)[:200]}")

        # ── Extraer datos del mensaje ─────────────────────────────────
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            # Puede ser un status update (delivered, read), no un mensaje
            return {"status": "ok"}

        msg = messages[0]
        from_number = msg.get("from", "")
        msg_type = msg.get("type", "")

        # ── Extraer texto según el tipo de mensaje ────────────────────
        if msg_type == "text":
            texto = msg.get("text", {}).get("body", "").strip()

        elif msg_type == "interactive":
            interactive = msg.get("interactive", {})
            itype = interactive.get("type", "")
            if itype == "button_reply":
                texto = interactive.get("button_reply", {}).get(
                    "id",
                    interactive.get("button_reply", {}).get("title", ""),
                )
            elif itype == "list_reply":
                texto = interactive.get("list_reply", {}).get("id", "")
            else:
                return {"status": "ok"}

        else:
            await wsp.enviar_texto(
                from_number,
                "Solo puedo procesar mensajes de texto por ahora. "
                "Escribe lo que necesitas o *Asesor* para hablar con una persona. 😊",
            )
            return {"status": "ok"}

        if not texto or not from_number:
            return {"status": "ok"}

        logger.info(f"[{from_number}] -> '{texto}'")

        # Verificar comando "Asesor" (prioridad máxima)
        if "asesor" in texto.lower():
            await gestor.activar_humano(from_number, wsp)
            return {"status": "ok"}

        # Procesar mensaje a través de la máquina de estados
        await gestor.procesar(from_number, texto, wsp)

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error procesando webhook: {e}", exc_info=True)
        return {"status": "error", "detail": str(e)}


# ── Endpoints del simulador local ────────────────────────────────────────────

@app.get("/simulator", tags=["Simulador"], response_class=HTMLResponse)
async def simulador():
    """
    Simulador visual de WhatsApp para pruebas locales.
    No requiere credenciales de WhatsApp para funcionar.
    """
    sim_path = Path(__file__).parent / "static" / "simulator.html"
    if sim_path.exists():
        return FileResponse(sim_path, media_type="text/html")
    return HTMLResponse("<h1>simulator.html no encontrado</h1>", status_code=404)


@app.post("/simulate", tags=["Simulador"])
async def simular_mensaje(req: SimulateRequest):
    """
    Procesa un mensaje como si viniera de WhatsApp y devuelve las respuestas del bot.
    Siempre captura las respuestas en memoria (funciona en producción y simulación).
    """
    phone = req.phone.strip() or "34600000001"
    texto = req.mensaje.strip()

    if not texto:
        return {"respuestas": []}

    logger.info(f"[SIM] [{phone}] -> '{texto}'")

    # Usamos un cliente simulador dedicado que SIEMPRE guarda en memoria
    sim_wsp = SimulatorWhatsAppClient()

    # Procesar el mensaje
    if "asesor" in texto.lower():
        await gestor.activar_humano(phone, sim_wsp)
    else:
        await gestor.procesar(phone, texto, sim_wsp)

    # Recoger todas las respuestas generadas
    respuestas = sim_wsp.obtener_mensajes_simulados(phone)

    return {"respuestas": respuestas, "phone": phone}


@app.get("/messages/{phone}", tags=["Simulador"])
async def obtener_mensajes(phone: str):
    """Obtiene mensajes pendientes del bot para un teléfono (polling del simulador)"""
    respuestas = wsp.obtener_mensajes_simulados(phone)
    return {"respuestas": respuestas}


# ── Endpoints de desarrollo ───────────────────────────────────────────────────

@app.get("/leads", tags=["Desarrollo"])
async def ver_leads():
    """
    Ver todos los leads capturados.
    Solo para desarrollo - eliminar o proteger en produccion.
    """
    leads_file = "data/leads.json"
    if os.path.exists(leads_file):
        with open(leads_file, "r", encoding="utf-8") as f:
            leads = json.load(f)
        return {"total": len(leads), "leads": leads}
    return {"total": 0, "leads": []}


@app.post("/reset/{phone}", tags=["Desarrollo"])
async def reiniciar_sesion(phone: str):
    """
    Reinicia la sesion de un usuario (util para pruebas).
    Solo para desarrollo.
    """
    if phone in gestor.sesiones:
        del gestor.sesiones[phone]
        from app.ai.groq_client import groq_ai
        groq_ai.clear_session(phone)
        return {"status": "ok", "message": f"Sesión de {phone} reiniciada"}
    return {"status": "ok", "message": f"No había sesión activa para {phone}"}
