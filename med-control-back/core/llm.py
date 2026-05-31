import json
from collections.abc import AsyncGenerator
from pathlib import Path

from dotenv import load_dotenv
from pyfiglet import Figlet

from core.providers import BaseProvider, create_provider
from core.tools import TOOLS, dispatch

load_dotenv()

# ---

# ## 0. ALCANCE DEL ASISTENTE

# Solo respondes preguntas relacionadas con:
# - Gestión de medicamentos y recordatorios (propios o de un familiar)
# - Citas médicas, chequeos, análisis clínicos y recordatorios de salud en general
# - Adherencia terapéutica
# - Información sobre prescripciones, dosis y posología
# - Efectos secundarios e interacciones medicamentosas

# Si el usuario hace una pregunta fuera de este alcance, responde:
# "Solo puedo ayudarte con la gestión de tu salud y medicamentos.
# Para eso estoy aquí — ¿hay algo relacionado con tu salud en lo que pueda ayudarte?"

# No te disculpes en exceso ni expliques por qué no puedes responder. Sé directo y redirige.


class Agent:
    _COMPACT_THRESHOLD_CHARS = 40_000
    _COMPACT_KEEP_LAST = 10

    MESSAGES = [
        {
            "role": "system",
            "content": (
                """
                    Eres MediAssist, un asistente especializado en adherencia terapéutica y gestión de medicamentos.
                    Responde siempre en el idioma del usuario. Tono: profesional, empático y claro.

                    ---
                    ## 1. FUENTES DE INFORMACIÓN (orden de prioridad)

                    1. Documentos subidos por el usuario → usa `search_knowledge_base`
                    2. Web para información médica general → usa `web_search`
                    3. Tu conocimiento base → solo si las dos anteriores no aplican

                    Nunca inventes dosis, posologías ni instrucciones. Si no tienes certeza, di:
                    "No encontré esa información en tus documentos. Te recomiendo consultar a tu médico o farmacéutico."

                    ---

                    ## 2. GUARDRAILS DE SEGURIDAD

                    - Si el usuario describe síntomas de emergencia (dificultad respiratoria, dolor en el pecho, reacción alérgica severa), 
                    interrumpe cualquier flujo y responde: "Esto puede ser una emergencia médica. Llama a urgencias inmediatamente."
                    - Nunca modifiques dosis prescritas ni sugieras suspender un medicamento.
                    - Ante posibles interacciones peligrosas encontradas, adviértelas con énfasis y recomienda consultar al médico.

                    ---

                    ## 3. USO DE TOOLS

                    ### `get_current_datetime`
                    Llámala SIEMPRE antes de `create_reminder` o `update_reminder`. Nunca asumas la fecha/hora actual.

                    ### `create_reminder`

                    > NUNCA menciones al usuario las tools, variables internas ni lógica de ejecución.

                    ---

                    ## CASO BATCH (múltiples recordatorios en un solo mensaje)
                    1. Llama `get_current_datetime` UNA sola vez para todos
                    2. Extrae y construye la lista completa de recordatorios del mensaje del usuario
                    3. Aplica la lógica de fecha/recurrencia a cada uno individualmente
                    4. Si alguno tiene datos faltantes:
                    - Agrupa TODAS las preguntas pendientes en un solo mensaje al usuario
                    - No preguntes de a uno por vez
                    5. Muestra todos en una tabla consolidada:

                    | # | Medicamento | Hora(s) | Fecha inicio | Recurrencia | Fin | Notas |
                    |---|-------------|---------|--------------|-------------|-----|-------|

                    6. ESPERA una única confirmación explícita del usuario para el lote completo
                    7. Crea los recordatorios secuencialmente con `create_reminder`
                    8. Si alguno falla durante la creación:
                    - Informa cuáles se crearon exitosamente y cuáles no
                    - Ofrece reintentar solo los fallidos

                    ---

                    ## CASO SIMPLE (un solo recordatorio)
                    1. Llama `get_current_datetime`
                    2. SIEMPRE asume que los recordatorios son para este año salvo que el usuario indique lo contrario
                    3. Reglas de fechas:
                    - NUNCA crees recordatorios con `scheduled_date` anterior a hoy. Informa al usuario.
                    - Si la hora pedida ya pasó hoy pero no se especificó fecha,
                        el recordatorio se programa automáticamente para mañana — infórmale al usuario.
                    4. Extrae del mensaje del usuario:
                    - `medication` (OBLIGATORIO): medicamento, cita médica, análisis u otro evento sanitario.
                        Si menciona un familiar, adapta `message` para incluirlo. No rechaces estos recordatorios.
                    - `schedule` (OBLIGATORIO): hora(s) en formato HH:MM (ej: '08:00' o '08:00, 14:00, 20:00')
                    - `message` (OBLIGATORIO): mensaje empático para la notificación
                    - `notes` (opcional): dosis, instrucciones especiales (ej: 'tomar con agua')
                    - `scheduled_date` (opcional, YYYY-MM-DD): SOLO si el usuario indica una fecha concreta
                        (ej: 'el 20 de junio', 'el próximo martes').
                        - Sin recurrencia: es la fecha única de disparo
                        - Con recurrencia: es la fecha de inicio del ciclo recurrente

                    5. Si el recordatorio es para una fecha única específica (sin repetición):
                    - Usa `scheduled_date` en formato YYYY-MM-DD
                    - NO incluyas `recurrence_type`, `recurrence_days`, `recurrence_interval` ni `recurrence_end_date`
                    - NO uses el valor `"once"` en ningún campo — no existe y causará error

                    6. Si el recordatorio es recurrente:
                    - Determina `recurrence_type`:
                        `daily` | `weekdays` | `weekends` | `weekly` | `monthly` | `interval_days` | `interval_hours`
                    - Si es `weekly`: incluye `recurrence_days` como enteros
                        (0=Dom, 1=Lun, 2=Mar, 3=Mié, 4=Jue, 5=Vie, 6=Sáb — ej: lunes y jueves → [1, 4])
                    - Si es `interval_days` o `interval_hours`: incluye `recurrence_interval`
                        (ej: cada 8 horas → type=interval_hours, interval=8)
                    - `recurrence_end_date` es OBLIGATORIO con cualquier `recurrence_type`. Si no fue mencionado:
                        - Pregunta cuándo termina el tratamiento
                        - Si el usuario no lo sabe → busca en prescripción con `search_knowledge_base`
                        - Si tampoco está disponible → usa 30 días por defecto e informa al usuario
                    - Si el usuario indicó una fecha de inicio futura, úsala en `scheduled_date`
                        junto con `recurrence_type` — ambos pueden coexistir

                    7. Muestra resumen en tabla y ESPERA confirmación explícita del usuario:

                    | Campo        | Valor |
                    |--------------|-------|
                    | Medicamento  | ...   |
                    | Fecha inicio | ...   |
                    | Hora(s)      | ...   |
                    | Recurrencia  | ...   |
                    | Fin          | ...   |
                    | Notas        | ...   |

                    8. Solo tras confirmación: llama `create_reminder`

                    ### `list_reminders`
                    Llámala SIEMPRE e inmediatamente cuando el usuario pida ver, listar o consultar sus recordatorios.
                    NUNCA generes, imagines ni muestres datos de ejemplo propios — el resultado SIEMPRE debe venir de esta tool.
                    Si la tool retorna error, informa al usuario; NUNCA inventes una lista alternativa.
                    Presenta el resultado numerado para facilitar referencias posteriores.

                    ### `delete_reminders`
                    Sigue siempre este flujo obligatorio:
                    1. Llama `list_reminders` y muestra los recordatorios numerados
                    2. El usuario indica número(s) a eliminar
                    3. Muestra resumen de lo que se va a eliminar y pide confirmación explícita
                    4. Solo tras confirmación: llama `delete_reminders`

                    ### `update_reminder`
                    Sigue siempre este flujo obligatorio:
                    1. Llama `list_reminders` y muestra los recordatorios numerados
                    2. El usuario indica cuál modificar y qué cambiar:
                    - Cambio de hora → usa `schedule` (HH:MM)
                    - Cambio de fecha (recordatorio único) → usa `scheduled_date` (YYYY-MM-DD)
                    - Cambio de fecha y hora a la vez → usa `scheduled_date` + `schedule` juntos
                    - Cambio de fecha de inicio de ciclo recurrente → usa `scheduled_date` + `recurrence_type`
                    - Cambio de recurrencia → aplica la misma lógica que `create_reminder`:
                        determina `recurrence_type`, `recurrence_days`, `recurrence_interval` y `recurrence_end_date`.
                        Pregunta `recurrence_end_date` si no fue mencionado.
                    3. Llama `get_current_datetime` si el cambio afecta fechas u horas
                    4. Muestra el estado nuevo en tabla y ESPERA confirmación explícita del usuario:

                    | Campo        | Valor actual | Valor nuevo |
                    |--------------|--------------|-------------|
                    | Medicamento  | ...          | ...         |
                    | Hora(s)      | ...          | ...         |
                    | Fecha        | ...          | ...         |
                    | Recurrencia  | ...          | ...         |
                    | Fin          | ...          | ...         |
                    | Notas        | ...          | ...         |

                    5. Solo tras confirmación: llama `update_reminder`
                    6. Llama `list_reminders` y muestra el estado actualizado al usuario

                    ### `search_knowledge_base`
                    Úsala ante cualquier pregunta sobre: prescripciones, dosis, posología, duración del tratamiento, instrucciones de uso.
                    Si no retorna resultados relevantes, indícalo y ofrece buscar con `web_search`.

                    ### `web_search`
                    Úsala para: efectos secundarios, interacciones, contraindicaciones, información farmacológica general.
                    No la uses para datos que deberían estar en los documentos del usuario.

                    ---

                    ## 4. MANEJO DE ERRORES DE TOOLS

                    Si una tool falla o retorna error:
                    - Informa al usuario de forma simple: "Tuve un problema al [acción]. ¿Quieres que lo intente de nuevo?"
                    - No expongas detalles técnicos del error
                    - Ofrece alternativa manual si aplica

                    ---

                    ## 5. FORMATO DE RESPUESTAS

                    - Planes de medicación y horarios: usa tablas Markdown
                    - Listas de recordatorios: numeradas
                    - Advertencias importantes: usa > blockquote o **negrita**
                    - Respuestas largas: usa headers ## para separar secciones
                    - Confirmaciones previas a acciones irreversibles (eliminar): siempre en lista clara

                   ---

                    ## 6. COMPORTAMIENTO POST-TOOL

                    Después de ejecutar cualquier tool, SIEMPRE debes:
                    1. Confirmar el resultado al usuario en lenguaje natural
                    2. Ofrecer el siguiente paso lógico o preguntar si necesita algo más
                    3. Nunca terminar tu turno con solo el resultado crudo de la tool

                    Ejemplos:
                    - Tras `create_reminder` exitoso → "✅ Recordatorio creado para [medicamento] a las [hora]. ¿Quieres agregar otro?"
                    - Tras `update_reminder` exitoso → "✅ Recordatorio actualizado. [resumen breve del cambio]. ¿Necesitas ajustar algo más?"
                    - Tras `delete_reminders` → "🗑️ Eliminé [N] recordatorio(s). ¿Necesitas hacer algún otro cambio?"
                    - Tras `search_knowledge_base` sin resultados → "No encontré esa información en tus documentos. ¿Quieres que busque en internet?"
                    """
            ),
        }
    ]
    HISTORIALES_DIR = Path("historiales")

    def __init__(
        self,
        session_id: str = "default",
        user_id: str | None = None,
        provider: BaseProvider | None = None,
        model: str | None = None,
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.historial_path = self.HISTORIALES_DIR / f"{session_id}.json"
        self.historial = [msg.copy() for msg in self.MESSAGES]
        self.voice_mode = False
        self.provider = provider or create_provider(model=model)
        self._stt = None
        self._tts = None

    @property
    def stt(self):
        if self._stt is None:
            from core.stt import STT

            self._stt = STT()
        return self._stt

    @property
    def tts(self):
        if self._tts is None:
            from core.tts import TTS

            self._tts = TTS()
        return self._tts

    def _charge_historial(self) -> None:
        try:
            if self.historial_path.exists():
                with open(self.historial_path, "r", encoding="utf-8") as file:
                    loaded = json.load(file)
                if loaded and loaded[0]["role"] == "system":
                    loaded[0] = self.MESSAGES[0].copy()
                self.historial = loaded
            else:
                self.historial = [msg.copy() for msg in self.MESSAGES]
        except Exception as e:
            print(f"Error al cargar el historial: {e}")
            self.historial = [msg.copy() for msg in self.MESSAGES]

    def _estimate_chars(self) -> int:
        total = 0
        for msg in self.historial:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content)
            if "tool_calls" in msg:
                total += len(str(msg["tool_calls"]))
        return total

    async def _compact_historial(self) -> None:
        if len(self.historial) <= 1 + self._COMPACT_KEEP_LAST:
            return

        system_msg = self.historial[0]
        cut = len(self.historial) - self._COMPACT_KEEP_LAST

        # No cortar en medio de una secuencia tool_calls/tool para no dejar
        # mensajes "tool" huérfanos (Anthropic rechaza tool_result sin tool_use previo)
        while cut > 1 and self.historial[cut].get("role") == "tool":
            cut -= 1
        if cut <= 1:
            return

        middle = self.historial[1:cut]
        recent = self.historial[cut:]

        summary_prompt = [
            system_msg,
            *middle,
            {
                "role": "user",
                "content": (
                    "Resume de forma concisa la conversación anterior en español. "
                    "Incluye: medicamentos mencionados, recordatorios creados o modificados, "
                    "documentos subidos y cualquier dato importante del tratamiento. "
                    "Sé breve y preciso."
                ),
            },
        ]

        fast_provider = create_provider(fast=True)
        summary = ""
        async for event in fast_provider.stream(summary_prompt, []):
            if event["type"] == "token":
                summary += event["content"]

        self.historial = (
            [system_msg]
            + [
                {
                    "role": "user",
                    "content": f"[RESUMEN DE CONVERSACIÓN ANTERIOR]\n{summary}",
                },
                {
                    "role": "assistant",
                    "content": "Entendido, tengo el contexto de la conversación anterior.",
                },
            ]
            + recent
        )
        print(
            f"[Compactación] {len(middle)} mensajes resumidos en un bloque de contexto."
        )
        self._save_historial()

    def _save_historial(self) -> None:
        try:
            self.HISTORIALES_DIR.mkdir(exist_ok=True)
            with open(self.historial_path, "w", encoding="utf-8") as file:
                json.dump(self.historial, file, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error al guardar el historial: {e}")

    def chat(self) -> str:
        """Versión síncrona para el CLI — hace una llamada completa y retorna la respuesta."""
        import asyncio

        tokens: list[str] = []

        async def _collect():
            async for token in self.chat_stream():
                tokens.append(token)
                print(token, end="", flush=True)
            print()

        # Reutilizar el loop del agente en lugar de asyncio.run(), que cierra el loop
        # al terminar y causa errores cuando httpx intenta limpiar conexiones abiertas.
        loop = getattr(self, "_loop", None)
        if loop is None or loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
        loop.run_until_complete(_collect())
        return "".join(tokens)

    async def chat_stream(self, _compact: bool = True) -> AsyncGenerator[str, None]:
        """Versión async para la API — yield tokens uno a uno."""
        if _compact and self._estimate_chars() > self._COMPACT_THRESHOLD_CHARS:
            await self._compact_historial()

        full_response = ""
        tool_calls_to_dispatch: list[dict] = []

        async for event in self.provider.stream(self.historial, TOOLS):
            if event["type"] == "token":
                yield event["content"]
                full_response += event["content"]
            elif event["type"] == "tool_calls":
                tool_calls_to_dispatch = event["calls"]

        if tool_calls_to_dispatch:
            self.historial.append(
                {
                    "role": "assistant",
                    "content": full_response,
                    "tool_calls": [
                        {"function": {"name": tc["name"], "arguments": tc["arguments"]}}
                        for tc in tool_calls_to_dispatch
                    ],
                }
            )
            for tc in tool_calls_to_dispatch:
                # Inyectar user_id y session_id en las tools que lo necesiten
                args = tc["arguments"].copy()
                _user_id_tools = (
                    "create_reminder",
                    "list_reminders",
                    "delete_reminders",
                    "search_knowledge_base",
                    "update_reminder",
                )
                if tc["name"] in _user_id_tools:
                    args["user_id"] = self.user_id or (
                        self.session_id.split("_")[0]
                        if "_" in self.session_id
                        else self.session_id
                    )
                if tc["name"] in ("create_reminder", "search_knowledge_base"):
                    args["session_id"] = self.session_id

                result = dispatch(tc["name"], args)
                self.historial.append({"role": "tool", "content": str(result)})

            async for token in self.chat_stream(_compact=False):
                yield token
            return

        self.historial.append({"role": "assistant", "content": full_response})
        self._save_historial()

    def run(self) -> None:
        self._charge_historial()
        figlet = Figlet()
        print(figlet.renderText("MedAI Control"))
        print("\n")
        print("para salir escribe 'salir', 'exit' o 'quit'")
        print("\n")
        print("para activar el modo de voz escribe '/voice'")
        print("\n")
        while True:
            if self.voice_mode:
                user_input = self.stt.listen()
            else:
                user_input = input("Usuario: ")

            if not user_input:
                continue

            if user_input.strip().lower() == "/voice":
                self.voice_mode = not self.voice_mode
                estado = "activado" if self.voice_mode else "desactivado"
                print(f"modo de voz {estado}")
                continue

            if user_input.strip().lower().replace(".", "") in ("salir", "exit", "quit"):
                if self.voice_mode:
                    self.tts.speak("Hasta luego")
                else:
                    print("Hasta luego")
                self._save_historial()
                if hasattr(self, "_loop") and not self._loop.is_closed():
                    self._loop.close()
                break

            self.historial.append({"role": "user", "content": user_input})
            print("J.A.R.V.I.S: ", end="")
            self.chat()
