"""
OCR pipeline for prescription images using Claude vision.
Accepts JPEG, PNG, WEBP, or PDF — no system dependencies required.
"""

import base64
import json
import os

import anthropic as anthropic_sdk


# ── Data models ────────────────────────────────────────────────────────────

class PrescriptionData:
    __slots__ = ("medication", "dose", "frequency", "duration", "prescribing_doctor", "raw_notes")

    def __init__(
        self,
        medication: str = "",
        dose: str | None = None,
        frequency: str | None = None,
        duration: str | None = None,
        prescribing_doctor: str | None = None,
        raw_notes: str | None = None,
    ):
        self.medication = medication
        self.dose = dose
        self.frequency = frequency
        self.duration = duration
        self.prescribing_doctor = prescribing_doctor
        self.raw_notes = raw_notes

    def to_dict(self) -> dict:
        return {
            "medication": self.medication,
            "dose": self.dose,
            "frequency": self.frequency,
            "duration": self.duration,
            "prescribing_doctor": self.prescribing_doctor,
            "raw_notes": self.raw_notes,
        }


class OCRResult:
    __slots__ = ("raw_text", "structured")

    def __init__(self, raw_text: str, structured: PrescriptionData):
        self.raw_text = raw_text
        self.structured = structured


# ── Prompt ─────────────────────────────────────────────────────────────────

_PROMPT = """Eres un asistente médico. Analiza esta receta médica y devuelve ÚNICAMENTE un JSON válido con estas claves:
- "raw_text": todo el texto que puedes leer en la imagen (string)
- "medication": nombre del medicamento (string — usa "" si no lo encuentras)
- "dose": dosis por toma, ej. "500mg" (string o null)
- "frequency": frecuencia de toma, ej. "cada 8 horas", "1 vez al día" (string o null)
- "duration": duración del tratamiento, ej. "7 días", "1 mes" (string o null)
- "prescribing_doctor": nombre del médico si aparece (string o null)
- "raw_notes": instrucciones adicionales o notas importantes (string o null)

Devuelve solo el JSON, sin explicaciones ni markdown."""


# ── Main entry point ───────────────────────────────────────────────────────

async def process_prescription(file_bytes: bytes, mimetype: str) -> OCRResult:
    """
    Extract structured data from a prescription using Claude vision.
    Accepts JPEG, PNG, WEBP, or PDF bytes.
    """
    client = anthropic_sdk.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    model = os.getenv("ANTHROPIC_FAST_MODEL", "claude-haiku-4-5-20251001")

    encoded = base64.standard_b64encode(file_bytes).decode("utf-8")

    if mimetype == "application/pdf":
        content_block: dict = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": encoded},
        }
    else:
        if mimetype == "image/jpg":
            mimetype = "image/jpeg"
        content_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": mimetype, "data": encoded},
        }

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [content_block, {"type": "text", "text": _PROMPT}],
                }
            ],
        )

        content = response.content[0].text.strip()

        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        data = json.loads(content)
        return OCRResult(
            raw_text=data.get("raw_text", ""),
            structured=PrescriptionData(
                medication=data.get("medication", ""),
                dose=data.get("dose"),
                frequency=data.get("frequency"),
                duration=data.get("duration"),
                prescribing_doctor=data.get("prescribing_doctor"),
                raw_notes=data.get("raw_notes"),
            ),
        )
    except Exception as e:
        return OCRResult(
            raw_text="",
            structured=PrescriptionData(medication="", raw_notes=f"Error al procesar la receta: {e}"),
        )
