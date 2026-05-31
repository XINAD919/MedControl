from fastapi import APIRouter, Depends, HTTPException

from core import db
from deps import CurrentUser, get_current_user, get_or_create_agent, session_store

router = APIRouter()


@router.get("/")
def list_sessions():
    return {"sessions": list(session_store.keys())}


@router.post("/{session_id}")
async def create_session(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    if session_id in session_store:
        raise HTTPException(status_code=409, detail="Session already exists")
    await get_or_create_agent(session_id, current_user.user_id)
    return {"session_id": session_id, "created": True}


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    if session_id != str(current_user.user_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    session_store.pop(session_id, None)
    await db.clear_session_messages(session_id)
    return {"session_id": session_id, "deleted": True}
