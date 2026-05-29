# 🔑 Guía de Credenciales — ORESNA WhatsApp Bot

Esta guía te explica paso a paso cómo obtener todas las credenciales necesarias para que el bot funcione con WhatsApp real.

---

## 1. 🤖 GEMINI API KEY (IA gratuita)

> **Completamente gratis.** Sin tarjeta de crédito.

### Pasos:

1. Ve a 👉 **https://aistudio.google.com/apikey**
2. Inicia sesión con tu cuenta de Google
3. Haz clic en **"Create API Key"**
4. Elige **"Create API key in new project"** (o selecciona uno existente)
5. Copia la clave — empieza por **`AIzaSy...`**

> ⚠️ **IMPORTANTE:** Si tu clave empieza por `AQ.` en lugar de `AIzaSy`, has copiado un token OAuth en lugar de una API Key. Repite el proceso y asegúrate de copiar la API Key de la tabla principal.

6. Pega la clave en tu `.env`:
```
GEMINI_API_KEY=AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

### Límites gratuitos (más que suficientes):
| Métrica | Límite gratuito |
|---------|----------------|
| Peticiones/minuto | 30 |
| Peticiones/día | 1.500 |
| Tokens/día | 1.000.000 |

---

## 2. 📱 WhatsApp Cloud API (Meta)

> Solo necesario para producción real. Para pruebas locales, usa el **simulador visual**.

### Paso 1: Crear cuenta en Meta for Developers

1. Ve a 👉 **https://developers.facebook.com**
2. Inicia sesión con tu cuenta de Facebook
3. Ve a **"Mis Apps"** → **"Crear App"**
4. Elige **"Empresa"** como tipo
5. Rellena el nombre (ej: "ORESNA Bot")

### Paso 2: Añadir WhatsApp a tu app

1. En el dashboard de tu app, haz clic en **"Añadir producto"**
2. Busca **"WhatsApp"** y haz clic en **"Configurar"**
3. Sigue el asistente de configuración

### Paso 3: Obtener las credenciales

En el panel de WhatsApp Business de tu app:

| Credencial | Dónde encontrarla | Variable `.env` |
|------------|------------------|-----------------|
| **Token de acceso temporal** | Sección "API Setup" → "Temporary access token" | `WHATSAPP_TOKEN` |
| **Phone Number ID** | Sección "API Setup" → "Phone number ID" | `PHONE_NUMBER_ID` |

> ⚠️ El token temporal **expira en 24 horas**. Para producción, necesitas un token permanente (requiere cuenta Business verificada).

### Paso 4: Configurar el webhook (requiere ngrok)

1. Instala ngrok: **https://ngrok.com/download**
2. Abre una nueva ventana de PowerShell y ejecuta:
   ```
   ngrok http 8000
   ```
3. Copia la URL que te da ngrok (ej: `https://abc123.ngrok.io`)
4. En Meta for Developers → WhatsApp → **Configuración** → **Webhook**:
   - **URL de callback**: `https://abc123.ngrok.io/webhook`
   - **Token de verificación**: el valor de `VERIFY_TOKEN` en tu `.env` (por defecto: `oresna_bot_verify_2024`)
5. Haz clic en **"Verificar y guardar"**
6. Suscríbete al evento **`messages`**

---

## 3. 📞 Número del Asesor (BOSS_PHONE)

El bot enviará una alerta a este número cuando un cliente pida hablar con un asesor.

- Formato: número internacional **sin el signo `+`**
- España: `34` + número → ej: `34671392073`

```
BOSS_PHONE=34671392073
```

> ⚠️ Este número debe estar **registrado en WhatsApp** y debe haber iniciado conversación con tu número de WhatsApp Business (Meta requiere que el destinatario haya aceptado mensajes).

---

## 4. ✅ Verificación del `.env` completo

Tu archivo `.env` debería tener este aspecto:

```env
WHATSAPP_TOKEN=EAAd...tu_token_real...
PHONE_NUMBER_ID=1234567890
VERIFY_TOKEN=oresna_bot_verify_2024
GEMINI_API_KEY=AIzaSyXXXXXXXXXXXXXXXXXXXXXX
BOSS_PHONE=34671392073
CATALOG_PATH=propiedades.csv
```

---

## 5. 🧪 Probar sin WhatsApp real

Para pruebas locales **no necesitas ninguna credencial de WhatsApp**. Solo necesitas la `GEMINI_API_KEY`.

1. Rellena solo `GEMINI_API_KEY` en el `.env`
2. Ejecuta `arrancar_bot.bat`
3. El navegador se abrirá automáticamente en **http://localhost:8000/simulator**
4. ¡Prueba el bot completo desde el navegador!

---

## 6. 🚀 Pasar a producción

Cuando quieras conectar WhatsApp real:

1. Añade el token real de Meta al `.env`
2. Configura ngrok y el webhook en Meta
3. Reinicia el bot
4. Escanea el QR de tu número de WhatsApp Business con el móvil

---

*Para soporte técnico, revisa los logs de la consola del bot.*
