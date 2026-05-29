"""
app/bot/conversation.py - Máquina de estados de la conversación inmobiliaria

Flujo completo:
  NUEVO → ESPERANDO_TIPO → ESPERANDO_ZONA → ESPERANDO_PRESUPUESTO
        → ESPERANDO_HABITACIONES → ESPERANDO_NOMBRE → ESPERANDO_EMAIL
        → LEAD_COMPLETO

  Cualquier estado → "Asesor" → HUMANO (bot pausado)
  Anti-bucle: 3 intentos fallidos en el mismo estado → HUMANO automático
"""
import json
import logging
import os
import re
from datetime import datetime
from enum import Enum

from app.ai.gemini_client import gemini_ai
from app.bot.rag_engine import motor_rag

logger = logging.getLogger(__name__)

LEADS_FILE = "data/leads.json"
MAX_INTENTOS_FALLIDOS = 3  # Tras 3 fallos consecutivos → escalar a asesor


class Estado(Enum):
    NUEVO = "nuevo"
    ESPERANDO_TIPO = "esperando_tipo"
    ESPERANDO_ZONA = "esperando_zona"
    ESPERANDO_PRESUPUESTO = "esperando_presupuesto"
    ESPERANDO_HABITACIONES = "esperando_habitaciones"
    ESPERANDO_NOMBRE = "esperando_nombre"
    ESPERANDO_EMAIL = "esperando_email"
    LEAD_COMPLETO = "lead_completo"
    HUMANO = "humano"


class Sesion:
    """Datos de la conversación de un usuario concreto"""

    def __init__(self, phone: str):
        self.phone = phone
        self.estado = Estado.NUEVO
        self.tipo: str | None = None           # 'venta', 'alquiler', 'venta_propia'
        self.zona: str | None = None
        self.presupuesto: int | None = None
        self.habitaciones: int | None = None
        self.nombre: str | None = None
        self.email: str | None = None
        self.creada: str = datetime.now().isoformat()
        self.intentos_fallidos: int = 0        # Contador anti-bucle

    def to_dict(self) -> dict:
        return {
            "telefono": self.phone,
            "nombre": self.nombre,
            "email": self.email,
            "tipo": self.tipo,
            "zona": self.zona,
            "presupuesto": self.presupuesto,
            "habitaciones": self.habitaciones,
            "creada": self.creada,
        }


class GestorSesiones:
    """Gestiona las sesiones activas y el flujo de conversación"""

    def __init__(self):
        self.sesiones: dict[str, Sesion] = {}

    def get(self, phone: str) -> Sesion:
        """Obtiene o crea la sesión de un usuario"""
        if phone not in self.sesiones:
            self.sesiones[phone] = Sesion(phone)
            logger.info(f"🆕 Nueva sesión creada para {phone}")
        return self.sesiones[phone]

    # ------------------------------------------------------------------
    # Anti-bucle: registrar fallo y escalar si se supera el límite
    # ------------------------------------------------------------------

    async def _registrar_fallo(self, phone: str, wsp) -> bool:
        """
        Incrementa el contador de intentos fallidos.
        Si supera MAX_INTENTOS_FALLIDOS, escala automáticamente a modo humano.

        Returns:
            True si se ha escalado (el llamador debe detenerse),
            False si aún quedan intentos.
        """
        sesion = self.get(phone)
        sesion.intentos_fallidos += 1
        restantes = MAX_INTENTOS_FALLIDOS - sesion.intentos_fallidos

        if sesion.intentos_fallidos >= MAX_INTENTOS_FALLIDOS:
            logger.warning(
                f"🔄 Anti-bucle activado para {phone} "
                f"({sesion.intentos_fallidos} intentos fallidos seguidos)"
            )
            await wsp.enviar_texto(
                phone,
                "😊 Veo que estamos teniendo dificultades para entendernos.\n\n"
                "Voy a conectarte con uno de nuestros asesores de *ORESNA* "
                "para que te ayude personalmente. ¡Estarán encantados de atenderte!",
            )
            await self.activar_humano(phone, wsp)
            return True

        if restantes == 1:
            await wsp.enviar_texto(
                phone,
                "💡 Si prefieres hablar directamente con una persona, escribe *Asesor*.",
            )
        return False

    def _reset_intentos(self, sesion: Sesion) -> None:
        """Reinicia el contador de intentos al avanzar de estado"""
        sesion.intentos_fallidos = 0

    # ------------------------------------------------------------------
    # Punto de entrada principal
    # ------------------------------------------------------------------

    async def procesar(self, phone: str, texto: str, wsp) -> None:
        """
        Procesa un mensaje entrante y genera la respuesta adecuada
        según el estado actual de la conversación.
        """
        sesion = self.get(phone)

        # Si el bot está pausado, ignorar todos los mensajes
        if sesion.estado == Estado.HUMANO:
            logger.info(f"⏸️  Bot pausado para {phone}, mensaje ignorado")
            return

        estado = sesion.estado

        # ── ESTADO 1: Usuario nuevo ──────────────────────────────────
        if estado == Estado.NUEVO:
            await wsp.enviar_bienvenida(phone)
            sesion.estado = Estado.ESPERANDO_TIPO

            # Si el primer mensaje ya indica el tipo, aprovechamos
            tipo = self._detectar_tipo(texto)
            if tipo:
                sesion.tipo = tipo
                self._reset_intentos(sesion)
                sesion.estado = Estado.ESPERANDO_ZONA
                await wsp.enviar_texto(
                    phone,
                    "📍 *¿En qué zona te interesa?*\n\n"
                    "Puedes indicar barrio, ciudad o zona concreta.\n"
                    "_(Ej: Centro, Chamberí, Salamanca, Las Rozas...)_",
                )

        # ── ESTADO 2: Esperando tipo de operación ────────────────────
        elif estado == Estado.ESPERANDO_TIPO:
            tipo = self._detectar_tipo(texto)
            if tipo:
                sesion.tipo = tipo
                self._reset_intentos(sesion)
                tipo_label = {"venta": "comprar", "alquiler": "alquilar", "venta_propia": "vender"}.get(tipo, tipo)
                sesion.estado = Estado.ESPERANDO_ZONA
                await wsp.enviar_texto(
                    phone,
                    f"✅ Perfecto, buscas *{tipo_label}*.\n\n"
                    "📍 *¿En qué zona te interesa?*\n"
                    "_(Ej: Centro, Chamberí, Salamanca, Las Rozas...)_",
                )
            else:
                escalado = await self._registrar_fallo(phone, wsp)
                if not escalado:
                    await wsp.enviar_texto(
                        phone,
                        "Por favor, indica si quieres *comprar*, *alquilar* o *vender* una propiedad. 🏠",
                    )

        # ── ESTADO 3: Esperando zona ─────────────────────────────────
        elif estado == Estado.ESPERANDO_ZONA:
            if len(texto.strip()) >= 2:
                sesion.zona = texto.strip()
                self._reset_intentos(sesion)
                sesion.estado = Estado.ESPERANDO_PRESUPUESTO
                await wsp.enviar_texto(
                    phone,
                    f"📍 Zona: *{sesion.zona}* ✅\n\n"
                    "💰 *¿Cuál es tu presupuesto máximo?*\n"
                    "_(Ej: 150.000€, 200000, 1.200€/mes...)_",
                )
            else:
                escalado = await self._registrar_fallo(phone, wsp)
                if not escalado:
                    await wsp.enviar_texto(
                        phone,
                        "Por favor, indícame la zona o ciudad que te interesa 📍",
                    )

        # ── ESTADO 4: Esperando presupuesto ──────────────────────────
        elif estado == Estado.ESPERANDO_PRESUPUESTO:
            presupuesto = self._extraer_numero(texto)
            if presupuesto and presupuesto > 0:
                sesion.presupuesto = presupuesto
                self._reset_intentos(sesion)
                sesion.estado = Estado.ESPERANDO_HABITACIONES
                await wsp.enviar_texto(
                    phone,
                    f"💰 Presupuesto: *{presupuesto:,}€* ✅\n\n"
                    "🛏 *¿Cuántas habitaciones necesitas?*\n"
                    "_(Ej: 1, 2, 3, 4 habitaciones...)_",
                )
            else:
                escalado = await self._registrar_fallo(phone, wsp)
                if not escalado:
                    await wsp.enviar_texto(
                        phone,
                        "Por favor, indícame el presupuesto en euros.\n"
                        "_(Ej: 150.000, 200000, 1200...)_",
                    )

        # ── ESTADO 5: Esperando habitaciones → búsqueda RAG ──────────
        elif estado == Estado.ESPERANDO_HABITACIONES:
            habitaciones = self._extraer_numero(texto)
            sesion.habitaciones = habitaciones
            self._reset_intentos(sesion)

            # Buscar en el catálogo real
            await wsp.enviar_texto(phone, "🔍 Buscando las mejores opciones para ti...")

            resultados = motor_rag.buscar(
                tipo=sesion.tipo,
                zona=sesion.zona,
                presupuesto_max=sesion.presupuesto,
                habitaciones=sesion.habitaciones,
            )

            query = (
                f"Busco {sesion.tipo} en {sesion.zona} "
                f"con presupuesto de {sesion.presupuesto}€ "
                f"y {sesion.habitaciones} habitaciones"
            )

            if resultados:
                contexto = self._formatear_propiedades(resultados)
                respuesta = await gemini_ai.responder(
                    phone, query, contexto_rag=contexto
                )
            else:
                # No hay resultados exactos: Gemini lo gestiona con elegancia
                respuesta = await gemini_ai.responder(
                    phone,
                    f"El cliente busca {sesion.tipo} en {sesion.zona} "
                    f"con presupuesto {sesion.presupuesto}€ y {sesion.habitaciones} habitaciones, "
                    "pero no hay propiedades exactas en catálogo. "
                    "Responde con empatía, ofrece buscar alternativas y sugiere hablar con un asesor.",
                )

            await wsp.enviar_texto(phone, respuesta)

            # Pasar a captura de lead
            sesion.estado = Estado.ESPERANDO_NOMBRE
            await wsp.enviar_texto(
                phone,
                "✉️ Para que nuestro agente te envíe más detalles y organice una visita sin compromiso,\n"
                "*¿Me indicas tu nombre completo?*",
            )

        # ── ESTADO 6: Esperando nombre ───────────────────────────────
        elif estado == Estado.ESPERANDO_NOMBRE:
            if len(texto.strip()) >= 2:
                sesion.nombre = texto.strip().title()
                self._reset_intentos(sesion)
                sesion.estado = Estado.ESPERANDO_EMAIL
                await wsp.enviar_texto(
                    phone,
                    f"Encantado, *{sesion.nombre}* 👋\n\n"
                    "📧 *¿Y tu correo electrónico?*\n"
                    "Te enviaremos los detalles y fotos de las propiedades seleccionadas.",
                )
            else:
                escalado = await self._registrar_fallo(phone, wsp)
                if not escalado:
                    await wsp.enviar_texto(
                        phone,
                        "Por favor, indícame tu nombre completo 😊",
                    )

        # ── ESTADO 7: Esperando email → lead guardado ─────────────────
        elif estado == Estado.ESPERANDO_EMAIL:
            if self._es_email_valido(texto):
                sesion.email = texto.strip().lower()
                self._reset_intentos(sesion)
                self._guardar_lead(sesion)
                sesion.estado = Estado.LEAD_COMPLETO

                await wsp.enviar_texto(
                    phone,
                    f"¡Perfecto, *{sesion.nombre}*! ✅\n\n"
                    "Hemos registrado tus datos correctamente. "
                    "Un agente de *ORESNA* se pondrá en contacto contigo a la mayor brevedad.\n\n"
                    "¿Hay algo más en lo que pueda ayudarte? "
                    "Si prefieres hablar con alguien ahora mismo, escribe *Asesor*. 👤",
                )
            else:
                escalado = await self._registrar_fallo(phone, wsp)
                if not escalado:
                    await wsp.enviar_texto(
                        phone,
                        "Por favor, introduce un email válido.\n_(Ej: nombre@correo.com)_",
                    )

        # ── ESTADO 8: Lead completo → conversación libre con IA ───────
        elif estado == Estado.LEAD_COMPLETO:
            # Detectar si quiere hacer una nueva búsqueda
            tipo_nuevo = self._detectar_tipo(texto)
            if tipo_nuevo:
                # Reiniciar flujo de búsqueda manteniendo datos personales
                sesion.tipo = tipo_nuevo
                sesion.zona = None
                sesion.presupuesto = None
                sesion.habitaciones = None
                sesion.estado = Estado.ESPERANDO_ZONA
                tipo_label = {"venta": "comprar", "alquiler": "alquilar", "venta_propia": "vender"}.get(tipo_nuevo, tipo_nuevo)
                await wsp.enviar_texto(
                    phone,
                    f"¡Claro! Vamos a buscar otra propiedad para *{tipo_label}*. 🏠\n\n"
                    "📍 *¿En qué zona te interesa esta vez?*",
                )
            else:
                respuesta = await gemini_ai.responder(phone, texto)
                await wsp.enviar_texto(phone, respuesta)

    # ------------------------------------------------------------------
    # Activar modo humano (asesor real)
    # ------------------------------------------------------------------

    async def activar_humano(self, phone: str, wsp) -> None:
        """
        Pausa el bot y alerta al jefe cuando el cliente pide un asesor.
        El bot quedará en pausa hasta que se reinicie la sesión.
        """
        sesion = self.get(phone)
        sesion.estado = Estado.HUMANO

        # Aviso al cliente
        await wsp.enviar_texto(
            phone,
            "👤 Entendido, he pausado el bot.\n\n"
            "Estoy avisando a un agente de *ORESNA* que se pondrá en contacto contigo "
            "en breve para continuar la conversación.\n\n"
            "¡Hasta pronto! 😊",
        )

        # Alerta al jefe con los datos del cliente
        await wsp.alertar_jefe(phone, sesion.to_dict())

        logger.info(f"🚨 Modo HUMANO activado para {phone}")

    # ------------------------------------------------------------------
    # Helpers privados
    # ------------------------------------------------------------------

    def _detectar_tipo(self, texto: str) -> str | None:
        """
        Detecta si el usuario quiere comprar, alquilar o vender.
        Maneja tanto texto libre como IDs de botones interactivos.
        """
        t = texto.lower().strip()

        # IDs de botones (configurados en whatsapp_client.py)
        if t == "comprar":
            return "venta"
        if t == "alquilar":
            return "alquiler"
        if t == "vender":
            return "venta_propia"

        # Texto libre
        if any(k in t for k in ["comprar", "compra", "adquirir", "quiero comprar"]):
            return "venta"
        if any(k in t for k in ["alquilar", "alquiler", "arrendar", "busco alquilar"]):
            return "alquiler"
        if any(k in t for k in ["vender", "vendo", "poner en venta"]):
            return "venta_propia"

        return None

    def _extraer_numero(self, texto: str) -> int | None:
        """
        Extrae un número de un texto con formato variado.
        Soporta: 150000, 150.000, 150k, 150 mil, 1200€/mes
        """
        t = texto.lower()

        # Eliminar símbolos de moneda y separadores
        t = t.replace("€", "").replace("$", "").replace("/mes", "")

        # Manejar sufijos "k" y "mil"
        t = re.sub(r"(\d+)\s*k\b", lambda m: str(int(m.group(1)) * 1000), t)
        t = re.sub(r"(\d+)\s*mil\b", lambda m: str(int(m.group(1)) * 1000), t)

        # Eliminar puntos usados como separador de miles y comas decimales
        t = t.replace(".", "").replace(",", "")

        # Extraer el primer número encontrado
        match = re.search(r"\d{1,10}", t)
        return int(match.group()) if match else None

    def _es_email_valido(self, email: str) -> bool:
        """Valida el formato básico de un email"""
        return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email.strip()))

    def _formatear_propiedades(self, propiedades: list[dict]) -> str:
        """Formatea las propiedades encontradas como contexto para Gemini"""
        lineas = []
        for i, p in enumerate(propiedades, 1):
            precio = p.get("precio", "N/A")
            precio_str = f"{precio:,}€" if isinstance(precio, (int, float)) else str(precio)
            lineas.append(
                f"PROPIEDAD {i}:\n"
                f"  Título: {p.get('titulo', 'N/A')}\n"
                f"  Zona: {p.get('zona', 'N/A')}\n"
                f"  Precio: {precio_str}\n"
                f"  Habitaciones: {p.get('habitaciones', 'N/A')}\n"
                f"  Baños: {p.get('banos', 'N/A')}\n"
                f"  Metros: {p.get('metros', 'N/A')}m²\n"
                f"  Descripción: {p.get('descripcion', 'N/A')}"
            )
        return "\n\n".join(lineas)

    def _guardar_lead(self, sesion: Sesion) -> None:
        """Guarda el lead capturado en data/leads.json"""
        lead = {
            "fecha": datetime.now().isoformat(),
            **sesion.to_dict(),
        }

        leads = []
        if os.path.exists(LEADS_FILE):
            try:
                with open(LEADS_FILE, "r", encoding="utf-8") as f:
                    leads = json.load(f)
            except (json.JSONDecodeError, IOError):
                leads = []

        leads.append(lead)

        os.makedirs(os.path.dirname(LEADS_FILE), exist_ok=True)
        with open(LEADS_FILE, "w", encoding="utf-8") as f:
            json.dump(leads, f, ensure_ascii=False, indent=2)

        logger.info(
            f"✅ Lead guardado: {sesion.nombre} | {sesion.email} | {sesion.phone}"
        )


# Instancia global (singleton)
gestor = GestorSesiones()
