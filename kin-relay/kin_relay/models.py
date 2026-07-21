"""Pydantic models for the kin-relay service endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class RegisterRequest(BaseModel):
    username: str
    public_key: str
    x25519_public_key: str
    endpoint: str


class LookupResponse(BaseModel):
    public_key: str
    x25519_public_key: str
    endpoint: str


class MailboxDeliverRequest(BaseModel):
    sender_username: str
    encrypted_blob: str


class InboxMessage(BaseModel):
    message_id: int
    sender_username: str
    encrypted_blob: str


class InboxResponse(BaseModel):
    messages: list[InboxMessage]


class InboxAckRequest(BaseModel):
    message_ids: list[int]
