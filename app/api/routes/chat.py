import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.schemas.chat import ChatRequest, ChatResponse
from app.conversation.session.store import get_session_store
from app.core.config.settings import get_settings
from app.retrieval.service import search_retrieval_material

router = APIRouter()


def _should_use_session_context(query: str) -> bool:
    cleaned = " ".join((query or "").lower().split())
    if not cleaned:
        return False
    follow_up_prefixes = (
        "what about",
        "how about",
        "and ",
        "also ",
        "then ",
        "next ",
    )
    follow_up_terms = {
        "it",
        "that",
        "those",
        "them",
        "this",
        "workflow",
        "steps",
        "process",
        "more",
        "details",
    }
    if cleaned.startswith(follow_up_prefixes):
        return True
    terms = cleaned.split()
    if any(term in follow_up_terms for term in terms):
        return True
    return False


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    settings = get_settings()
    store = get_session_store()

    merged_domain_context = (payload.domain_context or "").strip()
    if payload.session_id and _should_use_session_context(payload.query):
        session_context = store.get_recent_context(
            payload.session_id,
            max_messages=int(getattr(settings, "session_context_max_messages", 6)),
        )
        if session_context:
            merged_domain_context = (
                f"{merged_domain_context}\n\nRecent conversation context:\n{session_context}".strip()
                if merged_domain_context
                else f"Recent conversation context:\n{session_context}"
            )

    response = search_retrieval_material(
        query=payload.query,
        domain_context=merged_domain_context or None,
        top_k=max(3, int(getattr(settings, "retrieval_top_k", 3))),
    )

    if payload.session_id:
        store.append(payload.session_id, payload.query, role="user")
        store.append(payload.session_id, str(response.get("answer", "")), role="assistant")

    return {
        "answer": str(response.get("answer", "")),
        "citations": response.get("citations", []) or [],
        "confidence": float(response.get("answer_confidence", 0.0) or 0.0),
    }


@router.post("/stream")
def chat_stream(payload: ChatRequest) -> StreamingResponse:
    settings = get_settings()
    store = get_session_store()

    merged_domain_context = (payload.domain_context or "").strip()
    if payload.session_id and _should_use_session_context(payload.query):
        session_context = store.get_recent_context(
            payload.session_id,
            max_messages=int(getattr(settings, "session_context_max_messages", 6)),
        )
        if session_context:
            merged_domain_context = (
                f"{merged_domain_context}\n\nRecent conversation context:\n{session_context}".strip()
                if merged_domain_context
                else f"Recent conversation context:\n{session_context}"
            )

    response = search_retrieval_material(
        query=payload.query,
        domain_context=merged_domain_context or None,
        top_k=max(3, int(getattr(settings, "retrieval_top_k", 3))),
    )

    if payload.session_id:
        store.append(payload.session_id, payload.query, role="user")
        store.append(payload.session_id, str(response.get("answer", "")), role="assistant")

    answer = str(response.get("answer", ""))
    words = answer.split()

    def _stream() -> str:
        yield "event: start\n"
        yield "data: {}\n\n"
        for token in words:
            payload_json = json.dumps({"token": token + " "})
            yield "event: token\n"
            yield f"data: {payload_json}\n\n"
        final_payload = json.dumps(
            {
                "answer": answer,
                "citations": response.get("citations", []) or [],
                "confidence": float(response.get("answer_confidence", 0.0) or 0.0),
            }
        )
        yield "event: end\n"
        yield f"data: {final_payload}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
