"""
Envío de correos transaccionales usando smtplib (stdlib).
Mismas credenciales Gmail SMTP 587 que usa n8n para recordatorios.

Variables de entorno requeridas:
  SMTP_HOST       (default: smtp.gmail.com)
  SMTP_PORT       (default: 587)
  SMTP_USER       correo@gmail.com
  SMTP_PASSWORD   contraseña de aplicación Gmail
  SMTP_FROM_NAME  (default: MedControl)
  FRONTEND_URL    (default: http://localhost:3000)
"""

import logging
import os
import smtplib
import socket
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

_SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
_SMTP_USER = os.getenv("SMTP_USER", "")
_SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
_FROM_NAME = os.getenv("SMTP_FROM_NAME", "MedControl")


class _SMTP4(smtplib.SMTP):
    """SMTP over IPv4 only — avoids ENETUNREACH on IPv6-limited hosts (e.g. Railway)."""
    def _get_socket(self, host, port, timeout):
        addrs = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        ip, port_n = addrs[0][4]
        return socket.create_connection((ip, port_n), timeout, self.source_address)


class _SMTP_SSL4(smtplib.SMTP_SSL):
    """SMTP_SSL over IPv4 only — SSL hostname verification still uses the original hostname."""
    def _get_socket(self, host, port, timeout):
        addrs = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        ip, port_n = addrs[0][4]
        sock = socket.create_connection((ip, port_n), timeout, self.source_address)
        return self.context.wrap_socket(sock, server_hostname=self._host)


def _send(to: str, subject: str, html: str) -> None:
    """Envío sincrónico. Llamar desde BackgroundTask (hilo del executor de FastAPI)."""
    if not _SMTP_USER or not _SMTP_PASSWORD:
        logger.warning("SMTP_USER / SMTP_PASSWORD no configurados — email no enviado")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{_FROM_NAME} <{_SMTP_USER}>"
    msg["To"] = to
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        if _SMTP_PORT == 465:
            with _SMTP_SSL4(_SMTP_HOST, _SMTP_PORT) as server:
                server.login(_SMTP_USER, _SMTP_PASSWORD)
                server.sendmail(_SMTP_USER, to, msg.as_string())
        else:
            with _SMTP4(_SMTP_HOST, _SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.login(_SMTP_USER, _SMTP_PASSWORD)
                server.sendmail(_SMTP_USER, to, msg.as_string())
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
