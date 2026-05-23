import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import jwt
from fastapi import Header, HTTPException

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.llm import Agent


@dataclass
class CurrentUser:
    user_id: str
    role: str


def validate_token(token: Optional[str]) -> CurrentUser:
    """Valida un JWT HS256 firmado con AUTH_SECRET_INTERNAL.
    Sin secreto configurado (modo dev) acepta el token como user_id literal."""
    secret = os.getenv("AUTH_SECRET_INTERNAL")
    if not secret:
        return CurrentUser(
            user_id=token or "11111111-1111-1111-1111-111111111111",
            role="USER",
        )
    if not token:
        raise HTTPException(status_code=401, detail="Token requerido")
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return CurrentUser(user_id=payload["userId"], role=payload.get("role", "USER"))
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token inválido")


def get_current_user(authorization: Optional[str] = Header(None)) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No autenticado")
    return validate_token(authorization.removeprefix("Bearer "))


session_store: dict[str, Agent] = {}


async def get_or_create_agent(session_id: str, user_id: str) -> Agent:
    from core import db
    if session_id not in session_store:
        agent = Agent(session_id=session_id, user_id=user_id)
        session_store[session_id] = agent
        await db.get_or_create_session(user_id=user_id, session_id=session_id)
        db_messages = await db.load_messages(session_id)
        if db_messages:
            system_msg = agent.historial[0].copy()
            agent.historial = [system_msg] + [m for m in db_messages if m["role"] != "system"]
    else:
        await db.get_or_create_session(user_id=user_id, session_id=session_id)
    return session_store[session_id]
