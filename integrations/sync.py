"""Shared sync-state + external-object + sync-log helpers used by every
provider adapter. All writes/reads go through these helpers so the Hub UI
(Configure sheet) and the audit trail stay consistent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from db import get_session
from db_models import (
    ExternalObject,
    IntegrationSyncLog,
    ProviderSyncState,
)


# ── Sync-state cursors (Calendar watch, Sheets revisionId, HS pageToken) ──


def get_cursor(connection_id: str, resource_type: str, resource_id: str = "") -> str:
    with get_session() as sess:
        row = (
            sess.query(ProviderSyncState)
            .filter(
                ProviderSyncState.connection_id == connection_id,
                ProviderSyncState.resource_type == resource_type,
                ProviderSyncState.resource_id == resource_id,
            )
            .first()
        )
        return row.cursor if row else ""


def set_cursor(
    connection_id: str,
    resource_type: str,
    cursor: str,
    resource_id: str = "",
    meta: dict | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    with get_session() as sess:
        row = (
            sess.query(ProviderSyncState)
            .filter(
                ProviderSyncState.connection_id == connection_id,
                ProviderSyncState.resource_type == resource_type,
                ProviderSyncState.resource_id == resource_id,
            )
            .first()
        )
        if row is None:
            row = ProviderSyncState(
                connection_id=connection_id,
                resource_type=resource_type,
                resource_id=resource_id,
                cursor=cursor,
                last_synced_at=now,
                meta=meta or {},
            )
            sess.add(row)
        else:
            row.cursor = cursor
            row.last_synced_at = now
            if meta is not None:
                row.meta = meta


# ── External-object mapping (somtool entity ↔ provider id) ──


def set_external_id(
    org_id: str,
    entity_type: str,
    entity_id: str,
    provider: str,
    external_id: str,
    meta: dict | None = None,
) -> None:
    with get_session() as sess:
        row = (
            sess.query(ExternalObject)
            .filter(
                ExternalObject.entity_type == entity_type,
                ExternalObject.entity_id == entity_id,
                ExternalObject.provider == provider,
            )
            .first()
        )
        if row is None:
            row = ExternalObject(
                org_id=org_id,
                entity_type=entity_type,
                entity_id=entity_id,
                provider=provider,
                external_id=external_id,
                meta=meta or {},
            )
            sess.add(row)
        else:
            row.external_id = external_id
            if meta is not None:
                row.meta = meta


def get_external_id(entity_type: str, entity_id: str, provider: str) -> Optional[str]:
    with get_session() as sess:
        row = (
            sess.query(ExternalObject)
            .filter(
                ExternalObject.entity_type == entity_type,
                ExternalObject.entity_id == entity_id,
                ExternalObject.provider == provider,
            )
            .first()
        )
        return row.external_id if row else None


def delete_external_id(entity_type: str, entity_id: str, provider: str) -> bool:
    """Forget the mapping between a SOMTool entity and an external provider id.

    Returns True iff a row was deleted. Callers use this when the user deletes
    a queue action so the next push can't try to patch an event that no longer
    exists on our side.
    """
    with get_session() as sess:
        row = (
            sess.query(ExternalObject)
            .filter(
                ExternalObject.entity_type == entity_type,
                ExternalObject.entity_id == entity_id,
                ExternalObject.provider == provider,
            )
            .first()
        )
        if row is None:
            return False
        sess.delete(row)
        return True


def get_external_meta(entity_type: str, entity_id: str, provider: str) -> dict:
    """Return the meta dict we stashed when mapping this entity (Meet URL,
    htmlLink, ownerUserId, etag, etc.), or {} if no mapping exists.
    """
    with get_session() as sess:
        row = (
            sess.query(ExternalObject)
            .filter(
                ExternalObject.entity_type == entity_type,
                ExternalObject.entity_id == entity_id,
                ExternalObject.provider == provider,
            )
            .first()
        )
        return dict(row.meta or {}) if row else {}


def list_external_ids(entity_type: str, entity_id: str) -> dict[str, str]:
    with get_session() as sess:
        rows = (
            sess.query(ExternalObject)
            .filter(
                ExternalObject.entity_type == entity_type,
                ExternalObject.entity_id == entity_id,
            )
            .all()
        )
        return {r.provider: r.external_id for r in rows}


# ── Sync-log audit trail ──


def log_sync(
    connection_id: str,
    provider: str,
    action: str,
    status: str = "ok",
    rows_affected: int = 0,
    detail: str = "",
) -> None:
    with get_session() as sess:
        sess.add(
            IntegrationSyncLog(
                connection_id=connection_id,
                provider=provider,
                action=action,
                status=status,
                rows_affected=rows_affected,
                detail=(detail or "")[:4000],
            )
        )


def recent_logs(connection_id: str, limit: int = 20) -> list[IntegrationSyncLog]:
    with get_session() as sess:
        rows = (
            sess.query(IntegrationSyncLog)
            .filter(IntegrationSyncLog.connection_id == connection_id)
            .order_by(IntegrationSyncLog.created_at.desc())
            .limit(limit)
            .all()
        )
        for r in rows:
            sess.expunge(r)
        return rows
