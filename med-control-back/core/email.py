"""
Envío de correos transaccionales via webhook n8n.
n8n maneja el SMTP/Gmail directamente usando sus credenciales ya configuradas.

Variables de entorno requeridas:
  EMAIL_WEBHOOK_URL   URL del webhook n8n para envío de emails
                      (ej: https://tu-n8n.com/webhook/medai-email)
  SMTP_FROM_NAME      (default: MedControl)
  FRONTEND_URL        (default: http://localhost:3000)
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_EMAIL_WEBHOOK_URL = os.getenv("EMAIL_WEBHOOK_URL", "")
_FROM_NAME = os.getenv("SMTP_FROM_NAME", "MedControl")


def _send(to: str, subject: str, html: str) -> None:
    """Envía email via webhook n8n. Llamar desde BackgroundTask."""
    if not _EMAIL_WEBHOOK_URL:
        logger.warning("EMAIL_WEBHOOK_URL no configurado — email no enviado")
        return

    try:
        with httpx.Client(timeout=30) as client:
            r = client.post(
                _EMAIL_WEBHOOK_URL,
                json={"to": to, "subject": subject, "html": html},
            )
            r.raise_for_status()
        logger.info(f"Email enviado a {to}: {subject}")
    except Exception as exc:
        logger.error(f"Error enviando email a {to}: {exc}")


def send_invitation_existing_user(
    to: str,
    inviter_name: str,
    accept_url: str,
    reject_url: str,
) -> None:
    """
    Correo para usuario existente.
    accept_url = {FRONTEND_URL}/family/accept/{token}
    reject_url = {FRONTEND_URL}/family/reject/{token}
    """
    subject = f"{inviter_name} te invita a MedControl como cuidador/a"
    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <body style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:24px;color:#222">
      <h2 style="color:#2563eb">Invitación de cuidador/a</h2>
      <p>Hola,</p>
      <p><strong>{inviter_name}</strong> te ha invitado a ser su cuidador/a en MedControl.
      Como cuidador/a podrás ver su historial de medicamentos y recordatorios.</p>
      <div style="margin:28px 0;display:flex;gap:12px">
        <a href="{accept_url}"
           style="background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600">
          Aceptar invitación
        </a>
        &nbsp;&nbsp;
        <a href="{reject_url}"
           style="background:#f3f4f6;color:#374151;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600">
          Rechazar
        </a>
      </div>
      <p style="color:#9ca3af;font-size:12px">Este enlace expira en 72 horas.</p>
    </body>
    </html>
    """
    _send(to, subject, html)


def send_invitation_new_user(
    to: str,
    inviter_name: str,
    register_url: str,
) -> None:
    """
    Correo para usuario sin cuenta.
    register_url = {FRONTEND_URL}/register?caregiver_token={token}
    """
    subject = f"{inviter_name} te invita a unirte a MedControl"
    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <body style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:24px;color:#222">
      <h2 style="color:#2563eb">Invitación a MedControl</h2>
      <p>Hola,</p>
      <p><strong>{inviter_name}</strong> te ha invitado a unirte a MedControl como cuidador/a.
      Al crear tu cuenta podrás ver su historial de medicamentos y recordatorios.</p>
      <div style="margin:28px 0">
        <a href="{register_url}"
           style="background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600">
          Crear cuenta y aceptar
        </a>
      </div>
      <p style="color:#9ca3af;font-size:12px">Este enlace expira en 72 horas.</p>
    </body>
    </html>
    """
    _send(to, subject, html)
