"""
app/ai/groq_client.py - Cliente de Groq (Llama 3 100% gratis)
Usa el SDK: groq
Modelo: llama3-8b-8192 (súper rápido y gratuito)
"""
import asyncio
import logging

from groq import Groq

from app.core.config import settings

logger = logging.getLogger(__name__)

# Prompt de sistema: define la personalidad y reglas del bot inmobiliario
SYSTEM_PROMPT = """Eres AIA, la asistente inmobiliaria virtual de ORESNA Inmobiliaria.

PERSONALIDAD:
- Amable, profesional y concisa
- Usas emojis con moderación para hacer la conversación agradable
- Siempre hablas en español nativo de España

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


class GroqClient:
    """
    Cliente de Groq con gestión de historial por usuario.
    """

    def __init__(self):
        self._client: Groq | None = None
        self._initialized = False
        # Historial por usuario: phone -> list[dict]
        self.historiales: dict[str, list] = {}

    def _init(self) -> bool:
        """Inicializa el cliente Groq de forma lazy"""
        if self._initialized:
            return True

        if not settings.GROQ_API_KEY:
            logger.error(
                "GROQ_API_KEY no configurada. "
                "Obtén una GRATIS en https://console.groq.com/keys"
            )
            return False

        try:
            self._client = Groq(api_key=settings.GROQ_API_KEY)
            self._initialized = True
            logger.info("Groq (Llama 3) inicializado correctamente")
            return True
        except Exception as e:
            logger.error(f"Error iniciando Groq: {e}")
            return False

    def clear_session(self, phone: str) -> None:
        """Limpia el historial de un usuario"""
        self.historiales.pop(phone, None)

    def _get_historial(self, phone: str) -> list:
        """Obtiene o crea el historial de un usuario"""
        if phone not in self.historiales:
            self.historiales[phone] = [
                {"role": "system", "content": SYSTEM_PROMPT}
            ]
        return self.historiales[phone]

    def _llamar_groq(self, phone: str, prompt: str) -> str:
        """Llamada síncrona a Groq (se ejecuta en hilo separado desde async)"""
        historial = self._get_historial(phone)

        # Añadir mensaje del usuario al historial
        historial.append({"role": "user", "content": prompt})

        # Llamada a la API de Groq
        chat_completion = self._client.chat.completions.create(
            messages=historial,
            model="llama-3.1-8b-instant",
            temperature=0.7,
            max_tokens=400,
        )

        respuesta_texto = chat_completion.choices[0].message.content

        # Añadir respuesta del modelo al historial
        historial.append({"role": "assistant", "content": respuesta_texto})

        # Limitar historial a últimos 20 turnos (+1 del system prompt) para evitar tokens excesivos
        if len(historial) > 41:
            self.historiales[phone] = [historial[0]] + historial[-40:]

        return respuesta_texto

    async def responder(
        self,
        phone: str,
        mensaje: str,
        contexto_rag: str | None = None,
    ) -> str:
        """
        Genera una respuesta de IA para el usuario.
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
            respuesta = await asyncio.to_thread(self._llamar_groq, phone, prompt)
            return respuesta

        except Exception as e:
            logger.error(f"Error Groq para {phone}: {e}")
            return (
                "Lo siento, estoy teniendo dificultades técnicas. "
                "Por favor escribe *Asesor* y un agente de ORESNA te atenderá enseguida. 👤"
            )


# Instancia global (singleton)
groq_ai = GroqClient()
