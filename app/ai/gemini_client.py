"""
app/ai/gemini_client.py - Cliente de Google Gemini (IA gratuita)
Usa el SDK moderno: google-genai
Modelo: gemini-2.0-flash-lite (gratis: 30 RPM, 1.500 req/día, 1M tokens/día)
Obtén tu clave GRATIS en: https://aistudio.google.com/apikey
"""
import asyncio
import logging

from google import genai
from google.genai import types

from app.core.config import settings

logger = logging.getLogger(__name__)

# Prompt de sistema: define la personalidad y reglas del bot inmobiliario
SYSTEM_PROMPT = """Eres AIA, la asistente inmobiliaria virtual de ORESNA Inmobiliaria.

PERSONALIDAD:
- Amable, profesional y concisa
- Usas emojis con moderación para hacer la conversación agradable
- Siempre hablas en español

OBJETIVOS:
1. Ayudar al cliente a encontrar la propiedad perfecta de nuestro catálogo
2. Cuando tengas propiedades del catálogo, preséntalas de forma atractiva y clara
3. Guiar al cliente hacia dejar sus datos de contacto (nombre y email)
4. Si el cliente está frustrado, confundido o repite la misma pregunta, recuérdale que puede escribir "Asesor" para hablar con una persona real

REGLAS ESTRICTAS:
- Responde en máximo 4-5 líneas por mensaje (los mensajes de WhatsApp deben ser cortos)
- NUNCA inventes propiedades que no estén en el catálogo proporcionado
- NUNCA hagas promesas de precios o condiciones no confirmadas
- Si no tienes información suficiente, di que un agente le contactará
- Cuando presentes propiedades del catálogo, incluye siempre: precio, habitaciones, zona y descripción breve
- Si detectas que el cliente está dando vueltas, repitiendo preguntas o parece perdido, sugiere SIEMPRE escribir "Asesor" para hablar con una persona
- Si una pregunta no está relacionada con inmobiliaria, responde brevemente y redirige hacia las propiedades"""


class GeminiClient:
    """
    Cliente de Google Gemini con gestión de historial por usuario.
    Usa el nuevo SDK google-genai (v1.x).
    """

    def __init__(self):
        self._client: genai.Client | None = None
        self._initialized = False
        # Historial por usuario: phone -> list[Content]
        self.historiales: dict[str, list] = {}

    def _init(self) -> bool:
        """Inicializa el cliente Gemini de forma lazy"""
        if self._initialized:
            return True

        if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY.startswith(
            "PENDIENTE"
        ):
            logger.error(
                "❌ GEMINI_API_KEY no configurada. "
                "Obtén una GRATIS en https://aistudio.google.com/apikey"
            )
            return False

        try:
            self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
            self._initialized = True
            logger.info("✅ Gemini 2.0 Flash Lite (google-genai) inicializado")
            return True
        except Exception as e:
            logger.error(f"❌ Error iniciando Gemini: {e}")
            return False

    def clear_session(self, phone: str) -> None:
        """Limpia el historial de un usuario"""
        self.historiales.pop(phone, None)

    def _get_historial(self, phone: str) -> list:
        """Obtiene o crea el historial de un usuario"""
        if phone not in self.historiales:
            self.historiales[phone] = []
        return self.historiales[phone]

    def _llamar_gemini(self, phone: str, prompt: str) -> str:
        """Llamada síncrona a Gemini (se ejecuta en hilo separado desde async)"""
        historial = self._get_historial(phone)

        # Añadir mensaje del usuario al historial
        historial.append(
            types.Content(
                role="user",
                parts=[types.Part(text=prompt)],
            )
        )

        response = self._client.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents=historial,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=400,
                temperature=0.7,
            ),
        )

        respuesta_texto = response.text

        # Añadir respuesta del modelo al historial
        historial.append(
            types.Content(
                role="model",
                parts=[types.Part(text=respuesta_texto)],
            )
        )

        # Limitar historial a últimos 20 turnos para evitar tokens excesivos
        if len(historial) > 40:
            self.historiales[phone] = historial[-40:]

        return respuesta_texto

    async def responder(
        self,
        phone: str,
        mensaje: str,
        contexto_rag: str | None = None,
    ) -> str:
        """
        Genera una respuesta de IA para el usuario.

        Args:
            phone: Número de teléfono del usuario (para mantener historial)
            mensaje: Mensaje o contexto de la búsqueda del usuario
            contexto_rag: Propiedades encontradas para inyectar como contexto RAG

        Returns:
            Texto de respuesta de la IA
        """
        if not self._init():
            return (
                "Disculpa, estoy teniendo problemas técnicos en este momento. "
                "Escribe *Asesor* para hablar con una persona de nuestro equipo. 👤"
            )

        try:
            if contexto_rag:
                # Técnica RAG: inyectamos el catálogo real como contexto
                prompt = (
                    f"El cliente está buscando: {mensaje}\n\n"
                    f"PROPIEDADES DISPONIBLES EN NUESTRO CATÁLOGO:\n"
                    f"{contexto_rag}\n\n"
                    "Presenta estas propiedades al cliente de forma atractiva y breve. "
                    "Para cada propiedad incluye: precio, habitaciones, zona y un punto "
                    "destacado. Usa emojis. "
                    "Al final pregunta si alguna le interesa y si quiere que un agente le contacte."
                )
            else:
                prompt = mensaje

            # Ejecutamos en un hilo para no bloquear el event loop de FastAPI
            respuesta = await asyncio.to_thread(self._llamar_gemini, phone, prompt)
            return respuesta

        except Exception as e:
            logger.error(f"❌ Error Gemini para {phone}: {e}")
            return (
                "Lo siento, estoy teniendo dificultades técnicas. "
                "Por favor escribe *Asesor* y un agente de ORESNA te atenderá enseguida. 👤"
            )


# Instancia global (singleton)
gemini_ai = GeminiClient()
