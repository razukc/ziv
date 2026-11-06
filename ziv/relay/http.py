"""ziv.relay.http — the sender HTTP surface (docs/ARCHITECTURE.md §6).

Bearer tokens, scoped per sender; every refusal is JSON with a ``reason``
from ``ziv.wire``. Bodies are the wire models; nothing here invents a field.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from ziv.core.model import SCOPE_ADMIN, SCOPE_READ, SCOPE_SEND, Refusal
from ziv.haptics import tables
from ziv.wire import (
    CreateSender,
    DeviceView,
    EnrollBody,
    EnrollCodeResponse,
    EnrollResponse,
    Health,
    Prefs,
    Reason,
    ReplyView,
    ScheduleBody,
    ScheduleView,
    SenderView,
    State,
    SubmitUtterance,
    UtteranceView,
)

from .service import Principal, Relay

STATUS_FOR_REASON: dict[Reason, int] = {
    Reason.queue_full: 429,
    Reason.rate_limited: 429,
    Reason.over_budget: 413,
    Reason.unencodable: 422,
    Reason.bad_request: 422,
    Reason.unauthorized: 401,
    Reason.not_found: 404,
    Reason.conflict: 409,
    Reason.expired: 410,
    Reason.compose_failed: 502,
}


class RefusalError(Exception):
    def __init__(self, refusal: Refusal, status: int | None = None) -> None:
        super().__init__(refusal.message)
        self.refusal = refusal
        self.status = status or STATUS_FOR_REASON.get(refusal.reason, 400)


def refusal_response(refusal: Refusal, status: int | None = None) -> JSONResponse:
    return JSONResponse(status_code=status or STATUS_FOR_REASON.get(refusal.reason, 400), content=refusal.as_dict())


def _unwrap(result: Any):
    if isinstance(result, Refusal):
        raise RefusalError(result)
    return result


def get_relay(request: Request) -> Relay:
    return request.app.state.relay


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _principal(scope: str):
    async def dependency(request: Request, authorization: Annotated[str | None, Header()] = None) -> Principal:
        relay = get_relay(request)
        principal = relay.authenticate(_bearer(authorization))
        if principal is None:
            relay.event("auth_failed", reason=Reason.unauthorized, detail=request.url.path)
            raise RefusalError(Refusal(Reason.unauthorized, "a valid bearer token is required"))
        if not principal.allows(scope):
            raise RefusalError(Refusal(Reason.unauthorized, f"this token lacks the {scope} scope"))
        refusal = relay.rate_check(principal)
        if refusal is not None:
            raise RefusalError(refusal)
        return principal

    return dependency


Sends = Annotated[Principal, Depends(_principal(SCOPE_SEND))]
Reads = Annotated[Principal, Depends(_principal(SCOPE_READ))]
Admins = Annotated[Principal, Depends(_principal(SCOPE_ADMIN))]
RelayDep = Annotated[Relay, Depends(get_relay)]

router = APIRouter()


# --- utterances -------------------------------------------------------------


@router.post("/utterances", response_model=UtteranceView, status_code=201)
async def post_utterance(body: SubmitUtterance, principal: Sends, relay: RelayDep) -> UtteranceView:
    return _unwrap(relay.submit(principal, body))


@router.get("/utterances", response_model=list[UtteranceView])
async def list_utterances(principal: Reads, relay: RelayDep, state: State | None = None,
                    limit: Annotated[int, Query(ge=1, le=200)] = 100) -> list[UtteranceView]:
    return relay.list_utterances(principal.wearer, state, limit)


@router.get("/utterances/{id}", response_model=UtteranceView)
async def get_utterance(id: str, principal: Reads, relay: RelayDep) -> UtteranceView:
    return _unwrap(relay.get_utterance(principal.wearer, id))


@router.delete("/utterances/{id}", response_model=UtteranceView)
async def cancel_utterance(id: str, principal: Sends, relay: RelayDep) -> UtteranceView:
    return _unwrap(relay.cancel_utterance(principal.wearer, id))


# --- schedule ---------------------------------------------------------------


@router.post("/schedule", response_model=ScheduleView, status_code=201)
async def post_schedule(body: ScheduleBody, principal: Sends, relay: RelayDep) -> ScheduleView:
    return _unwrap(relay.add_schedule(principal, body))


@router.get("/schedule", response_model=list[ScheduleView])
async def list_schedule(principal: Reads, relay: RelayDep) -> list[ScheduleView]:
    return relay.list_schedule(principal.wearer)


@router.get("/schedule/{id}", response_model=ScheduleView)
async def get_schedule(id: int, principal: Reads, relay: RelayDep) -> ScheduleView:
    return _unwrap(relay.get_schedule(principal.wearer, id))


@router.delete("/schedule/{id}", response_model=ScheduleView)
async def delete_schedule(id: int, principal: Sends, relay: RelayDep) -> ScheduleView:
    return _unwrap(relay.delete_schedule(principal.wearer, id))


# --- prefs ------------------------------------------------------------------


@router.get("/prefs", response_model=Prefs)
async def get_prefs(principal: Reads, relay: RelayDep) -> Prefs:
    return relay.get_prefs(principal.wearer)


@router.put("/prefs", response_model=Prefs)
async def put_prefs(body: Prefs, principal: Sends, relay: RelayDep) -> Prefs:
    return relay.set_prefs(principal.wearer, body)


# --- replies ----------------------------------------------------------------


@router.get("/replies", response_model=list[ReplyView])
async def list_replies(principal: Reads, relay: RelayDep, undelivered: bool = False,
                 limit: Annotated[int, Query(ge=1, le=200)] = 100) -> list[ReplyView]:
    return relay.list_replies(principal.wearer, undelivered_only=undelivered, limit=limit)


# --- devices ----------------------------------------------------------------


@router.get("/devices", response_model=list[DeviceView])
async def list_devices(principal: Reads, relay: RelayDep) -> list[DeviceView]:
    return relay.list_devices(principal.wearer)


@router.post("/devices/enroll-code", response_model=EnrollCodeResponse, status_code=201)
async def post_enroll_code(principal: Admins, relay: RelayDep) -> EnrollCodeResponse:
    return relay.enroll_code(principal.wearer)


@router.post("/devices/enroll", response_model=EnrollResponse, status_code=201)
async def post_enroll(body: EnrollBody, relay: RelayDep) -> EnrollResponse:
    """The enrollment handshake: public, gated by the short-lived code."""
    return _unwrap(relay.enroll(body))


# --- senders ----------------------------------------------------------------


@router.post("/senders", response_model=SenderView, status_code=201)
async def post_sender(body: CreateSender, principal: Admins, relay: RelayDep) -> SenderView:
    return relay.create_sender(principal.wearer, body)


@router.get("/senders", response_model=list[SenderView])
async def list_senders(principal: Admins, relay: RelayDep) -> list[SenderView]:
    return relay.list_senders(principal.wearer)


# --- public -----------------------------------------------------------------


@router.get("/spec")
async def get_spec() -> Response:
    """The timing spec verbatim, as the generated tables carry it."""
    return JSONResponse(tables.SPEC)


@router.get("/health", response_model=Health)
async def get_health(relay: RelayDep) -> Health:
    return relay.health()
