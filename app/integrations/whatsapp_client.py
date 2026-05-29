"""
app/integrations/whatsapp_client.py - Comunicación con WhatsApp Cloud API
Gestiona el envío de mensajes de texto, botones interactivos y alertas al jefe.

Modo simulación: si WHATSAPP_TOKEN está vacío o es "SIMULACION",
los mensajes se almacenan en memoria en lugar de enviarse a Meta API.
"""
import httpx
import logging
from collections import defaultdict
from app.core.config import settings

logger = logging.getLogger(__name__)

WHATSAPP_API_URL = (
    f"https://graph.facebook.com/v20.0/{settings.PHONE_NUMBER_ID}/messages"
)
HEADERS = {
    "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
    "Content-Type": "application/json",
}

# Modo simulación: True si no hay token real configurado
MODO_SIMULACION = not settings.WHATSAPP_TOKEN or settings.WHATSAPP_TOKEN in ("", "SIMULACION", "tu_token_de_meta_aqui")


class WhatsAppClient:
    """Cliente para la WhatsApp Cloud API de Meta"""

    def __init__(self):
        # Cola de mensajes salientes para el simulador (phone -> list[str])
        self._bandeja_salida: dict[str, list[str]] = defaultdict(list)

        if MODO_SIMULACION:
            logger.info("🧪 Modo SIMULACIÓN activo (sin WhatsApp real)")
        else:
            logger.info("📱 Modo PRODUCCIÓN activo (WhatsApp Cloud API)")

    def obtener_mensajes_simulados(self, phone: str) -> list[str]:
        """
        Devuelve y vacía la bandeja de mensajes pendientes para un teléfono.
        Solo usado por el simulador local.
        """
        mensajes = list(self._bandeja_salida[phone])
        self._bandeja_salida[phone].clear()
        return mensajes

    async def _post(self, payload: dict) -> httpx.Response | None:
        """Envía una petición POST a la API de WhatsApp (o simula si no hay token)"""
        if MODO_SIMULACION:
            # En modo simulación solo logueamos, no enviamos nada a Meta
            to = payload.get("to", "unknown")
            logger.debug(f"[SIMULACIÓN] Mensaje para {to}: {payload}")
            return None

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(WHATSAPP_API_URL, json=payload, headers=HEADERS)
            if resp.status_code != 200:
                logger.error(
                    f"❌ WhatsApp API error [{resp.status_code}]: {resp.text}"
                )
            else:
                logger.debug(f"✅ Mensaje enviado a {payload.get('to')}")
            return resp

    async def enviar_texto(self, to: str, texto: str) -> None:
        """Envía un mensaje de texto simple (o lo guarda en simulación)"""
        if MODO_SIMULACION:
            # Guardar en bandeja para que el simulador web lo recoja
            self._bandeja_salida[to].append(texto)
            logger.info(f"[SIM] → [{to}]: {texto[:80]}...")
            return

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": texto, "preview_url": False},
        }
        await self._post(payload)

    async def enviar_bienvenida(self, to: str) -> None:
        """
        Envía mensaje de bienvenida con 3 botones interactivos:
        Comprar | Alquilar | Vender
        En modo simulación, guarda el mensaje de texto equivalente.
        """
        if MODO_SIMULACION:
            # En simulación enviamos texto equivalente + los botones como texto
            bienvenida = (
                "🏠 *ORESNA Inmobiliaria*\n\n"
                "¡Hola! Soy *AIA*, tu asistente inmobiliaria virtual 👋\n\n"
                "Estoy aquí para ayudarte a encontrar la propiedad perfecta "
                "o gestionar la venta de la tuya.\n\n"
                "*¿En qué puedo ayudarte hoy?*\n\n"
                "👉 Escribe: *Comprar*, *Alquilar* o *Vender*\n"
                "_(O pulsa uno de los botones rápidos)_"
            )
            self._bandeja_salida[to].append(bienvenida)
            logger.info(f"[SIM] → [{to}]: Bienvenida enviada")
            return

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "header": {"type": "text", "text": "🏠 ORESNA Inmobiliaria"},
                "body": {
                    "text": (
                        "¡Hola! Soy *AIA*, tu asistente inmobiliaria virtual 👋\n\n"
                        "Estoy aquí para ayudarte a encontrar la propiedad perfecta "
                        "o gestionar la venta de la tuya.\n\n"
                        "*¿En qué puedo ayudarte hoy?*"
                    )
                },
                "footer": {
                    "text": "Escribe 'Asesor' para hablar con una persona"
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {"id": "comprar", "title": "🔑 Comprar"},
                        },
                        {
                            "type": "reply",
                            "reply": {"id": "alquilar", "title": "🏠 Alquilar"},
                        },
                        {
                            "type": "reply",
                            "reply": {"id": "vender", "title": "💶 Vender"},
                        },
                    ]
                },
            },
        }
        await self._post(payload)

    async def alertar_jefe(self, cliente_phone: str, lead: dict) -> None:
        """
        Envía una alerta al número del jefe cuando un cliente pide hablar
        con un asesor humano. Si BOSS_PHONE no está configurado, solo loguea.
        """
        nombre = lead.get("nombre") or "Sin registrar"
        email = lead.get("email") or "Sin registrar"
        tipo = lead.get("tipo") or "Sin especificar"
        zona = lead.get("zona") or "Sin especificar"
        presupuesto = lead.get("presupuesto")
        presupuesto_str = f"{presupuesto:,}€" if presupuesto else "Sin especificar"

        mensaje = (
            "🚨 *ALERTA: CLIENTE PIDE ASESOR*\n\n"
            f"📱 Teléfono: +{cliente_phone}\n"
            f"👤 Nombre: {nombre}\n"
            f"📧 Email: {email}\n"
            f"🏠 Operación: {tipo}\n"
            f"📍 Zona: {zona}\n"
            f"💰 Presupuesto: {presupuesto_str}\n\n"
            "⚡ _El bot está PAUSADO. Continúa la conversación manualmente._"
        )

        if MODO_SIMULACION:
            logger.warning(
                f"🚨 [SIM] ALERTA JEFE:\n{mensaje}"
            )
            # También guardarlo en la bandeja del jefe si está configurado
            if settings.BOSS_PHONE:
                self._bandeja_salida[settings.BOSS_PHONE].append(mensaje)
            return

        if not settings.BOSS_PHONE:
            logger.warning(
                "⚠️  BOSS_PHONE no configurado. No se puede enviar alerta al jefe."
            )
            logger.warning(f"📋 Datos del cliente: {lead}")
            return

        payload = {
            "messaging_product": "whatsapp",
            "to": settings.BOSS_PHONE,
            "type": "text",
            "text": {"body": mensaje},
        }
        await self._post(payload)
        logger.info(f"🔔 Alerta enviada al jefe ({settings.BOSS_PHONE})")


class SimulatorWhatsAppClient:
    """
    Cliente WhatsApp que SIEMPRE almacena mensajes en memoria.
    Usado exclusivamente por el endpoint /simulate para que el simulador
    web pueda funcionar incluso cuando hay un token de WhatsApp real configurado.
    """

    def __init__(self):
        self._bandeja: dict[str, list[str]] = defaultdict(list)

    def obtener_mensajes_simulados(self, phone: str) -> list[str]:
        """Devuelve y vacía los mensajes almacenados para un teléfono"""
        mensajes = list(self._bandeja[phone])
        self._bandeja[phone].clear()
        return mensajes

    async def enviar_texto(self, to: str, texto: str) -> None:
        self._bandeja[to].append(texto)
        logger.info(f"[SIM] → [{to}]: {texto[:80]}")

    async def enviar_bienvenida(self, to: str) -> None:
        bienvenida = (
            "🏠 *ORESNA Inmobiliaria*\n\n"
            "¡Hola! Soy *AIA*, tu asistente inmobiliaria virtual 👋\n\n"
            "Estoy aquí para ayudarte a encontrar la propiedad perfecta "
            "o gestionar la venta de la tuya.\n\n"
            "*¿En qué puedo ayudarte hoy?*\n\n"
            "👉 Escribe: *Comprar*, *Alquilar* o *Vender*\n"
            "_(O pulsa uno de los botones rápidos)_"
        )
        self._bandeja[to].append(bienvenida)
        logger.info(f"[SIM] → [{to}]: Bienvenida enviada")

    async def alertar_jefe(self, cliente_phone: str, lead: dict) -> None:
        nombre = lead.get("nombre") or "Sin registrar"
        tipo = lead.get("tipo") or "Sin especificar"
        zona = lead.get("zona") or "Sin especificar"
        presupuesto = lead.get("presupuesto")
        presupuesto_str = f"{presupuesto:,}€" if presupuesto else "Sin especificar"
        mensaje = (
            f"🚨 ALERTA: CLIENTE PIDE ASESOR\n"
            f"📱 Tel: +{cliente_phone} | 👤 {nombre}\n"
            f"🏠 {tipo} en {zona} · 💰 {presupuesto_str}\n"
            "⚡ Bot PAUSADO. El asesor debe contactar manualmente."
        )
        logger.warning(f"[SIM] ALERTA JEFE: {mensaje}")
        if settings.BOSS_PHONE:
            self._bandeja[settings.BOSS_PHONE].append(mensaje)
