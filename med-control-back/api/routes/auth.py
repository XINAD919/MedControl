import logging
import os
from typing import Optional

import bcrypt
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from core.supabase_client import get_supabase

router = APIRouter()
logger = logging.getLogger(__name__)

def _check_secret(x_auth_secret: Optional[str]) -> None:
    expected = os.getenv("AUTH_SECRET_INTERNAL")
    if expected and x_auth_secret != expected:
        raise HTTPException(status_code=401, detail="No autorizado")


# ── Modelos ──────────────────────────────────────────────────────────────────

class OAuthUserRequest(BaseModel):
    email: str
    provider: str
    name: Optional[str] = None


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = None
    caregiver_token: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    id: str
    role: str


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _find_or_build_username(client, email: str) -> str:
    base = email.split("@")[0].lower()
    username, suffix = base, 0
    while True:
        check = await client.table("users").select("id").eq("username", username).maybe_single().execute()
        if not (check and check.data):
            return username
        suffix += 1
        username = f"{base}{suffix}"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/auth/oauth-user", response_model=AuthResponse, tags=["Auth"])
async def find_or_create_oauth_user(
    payload: OAuthUserRequest,
    x_auth_secret: Optional[str] = Header(None),
):
    """Server-to-server: busca o crea usuario por email (Google / Azure AD)."""
    _check_secret(x_auth_secret)
    if not payload.email:
        raise HTTPException(status_code=400, detail="Email requerido")

    client = get_supabase()
    res = await client.table("users").select("id, role").eq("email", payload.email).maybe_single().execute()
    if res and res.data:
        logger.info(f"OAuth login: usuario existente {res.data['id']}")
        return AuthResponse(id=res.data["id"], role=res.data["role"])

    username = await _find_or_build_username(client, payload.email)
    res2 = await client.table("users").insert({
        "username": username,
        "email": payload.email,
        "preferences": {"name": payload.name or username},
        "role": "USER",
    }).execute()
    user_id = res2.data[0]["id"]
    logger.info(f"OAuth: nuevo usuario creado {user_id} para {payload.email}")
    return AuthResponse(id=user_id, role="USER")


@router.post("/auth/register", response_model=AuthResponse, tags=["Auth"])
async def register(
    payload: RegisterRequest,
    x_auth_secret: Optional[str] = Header(None),
):
    """Registro con email + contraseña. Devuelve {id, role} al completarse."""
    _check_secret(x_auth_secret)
    if not payload.email or not payload.password:
        raise HTTPException(status_code=400, detail="Email y contraseña requeridos")

    client = get_supabase()
    existing = await client.table("users").select("id").eq("email", payload.email).maybe_single().execute()
    if existing and existing.data:
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese email")

    # Determinar rol: CAREGIVER si hay un caregiver_token válido
    role = "USER"
    invitation = None
    if payload.caregiver_token:
        from core.db import get_invitation_by_token
        from datetime import datetime, timezone
        inv = await get_invitation_by_token(payload.caregiver_token)
        if inv and inv.get("status") == "pending":
            exp_raw = str(inv["expires_at"]).replace("Z", "+00:00")
            exp = datetime.fromisoformat(exp_raw)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) <= exp:
                role = "CAREGIVER"
                invitation = inv

    password_hash = bcrypt.hashpw(payload.password.encode(), bcrypt.gensalt()).decode()
    username = await _find_or_build_username(client, payload.email)
    res = await client.table("users").insert({
        "username": username,
        "email": payload.email,
        "password_hash": password_hash,
        "preferences": {"name": payload.name or username},
        "role": role,
    }).execute()
    user_id = res.data[0]["id"]

    # Si hay invitación válida, crear la vinculación y marcar aceptada
    if invitation:
        from core.db import create_family_member, update_invitation_status
        await create_family_member(patient_id=invitation["inviter_id"], caregiver_id=user_id)
        await update_invitation_status(payload.caregiver_token, "accepted")
        logger.info(f"Registro cuidador: {user_id} vinculado al paciente {invitation['inviter_id']}")

    logger.info(f"Registro: nuevo usuario {user_id} ({role}) para {payload.email}")
    return AuthResponse(id=user_id, role=role)


@router.post("/auth/login", response_model=AuthResponse, tags=["Auth"])
async def login(
    payload: LoginRequest,
    x_auth_secret: Optional[str] = Header(None),
):
    """Login con email + contraseña. Devuelve {id, role} si las credenciales son correctas."""
    _check_secret(x_auth_secret)

    client = get_supabase()
    res = await client.table("users").select("id, role, password_hash").eq("email", payload.email).maybe_single().execute()

    if not (res and res.data) or not res.data.get("password_hash"):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    if not bcrypt.checkpw(payload.password.encode(), res.data["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    logger.info(f"Login: {res.data['id']}")
    return AuthResponse(id=res.data["id"], role=res.data["role"])
