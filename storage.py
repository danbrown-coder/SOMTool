"""Object storage wrapper — S3 / R2 / Backblaze compatible via boto3.

Falls back to the local filesystem (data/uploads/) when S3 isn't configured,
so dev-only installs keep working with no external dependencies.

All uploads are recorded in the `files` table. Use `upload_fileobj` from route
handlers that receive `werkzeug.datastructures.FileStorage`.
"""
from __future__ import annotations

import mimetypes
import os
import shutil
from pathlib import Path
from typing import BinaryIO, Optional
from urllib.parse import quote

from db import get_session
from db_models import FileAsset
from models import new_id
from org_manager import current_org_id


LOCAL_UPLOAD_DIR = Path(__file__).resolve().parent / "data" / "uploads"


def _s3_configured() -> bool:
    return bool(os.environ.get("S3_BUCKET") and os.environ.get("S3_ACCESS_KEY") and os.environ.get("S3_SECRET_KEY"))


def _client():
    if not _s3_configured():
        return None
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        return None
    endpoint = os.environ.get("S3_ENDPOINT", "").strip() or None
    region = os.environ.get("S3_REGION", "auto") or "auto"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", ""),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", ""),
        config=Config(signature_version="s3v4"),
    )


def _public_url_for(key: str) -> Optional[str]:
    base = os.environ.get("S3_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if base:
        return f"{base}/{quote(key)}"
    return None


def upload_fileobj(
    fileobj: BinaryIO,
    *,
    filename: str,
    purpose: str = "misc",
    event_id: str | None = None,
    owner_user_id: str | None = None,
    content_type: str | None = None,
) -> FileAsset:
    """Upload a file-like object and record it in `files`."""
    org_id = current_org_id()
    fid = new_id()
    safe_name = Path(filename).name or fid
    key = f"{org_id}/{purpose}/{fid}-{safe_name}"
    mime = content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"

    data = fileobj.read()
    size = len(data)

    bucket = os.environ.get("S3_BUCKET", "")
    public_url: Optional[str] = None

    if _s3_configured():
        client = _client()
        if client is None:
            raise RuntimeError("S3 SDK unavailable")
        client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=mime)
        public_url = _public_url_for(key)
    else:
        # Local fallback
        LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = LOCAL_UPLOAD_DIR / f"{fid}-{safe_name}"
        dest.write_bytes(data)
        bucket = "local"
        public_url = f"/uploads/{dest.name}"

    asset = FileAsset(
        id=fid,
        org_id=org_id,
        owner_user_id=owner_user_id,
        event_id=event_id,
        purpose=purpose,
        s3_key=key,
        bucket=bucket,
        filename=safe_name,
        mime=mime,
        size_bytes=size,
        public_url=public_url,
    )
    with get_session() as sess:
        sess.add(asset)
        sess.flush()
        sess.expunge(asset)
    return asset


def presigned_url(file_id: str, expires_in: int = 900) -> Optional[str]:
    """Get a time-limited URL for a private file, or the public URL if already public."""
    with get_session() as sess:
        row = sess.get(FileAsset, file_id)
        if row is None:
            return None
        if row.public_url and not row.public_url.startswith("/uploads/"):
            return row.public_url
        if row.bucket == "local":
            return row.public_url
        client = _client()
        if client is None:
            return None
        try:
            return client.generate_presigned_url(
                "get_object",
                Params={"Bucket": row.bucket, "Key": row.s3_key},
                ExpiresIn=expires_in,
            )
        except Exception:
            return None


def delete_file(file_id: str) -> bool:
    with get_session() as sess:
        row = sess.get(FileAsset, file_id)
        if row is None:
            return False
        if row.bucket == "local":
            try:
                (LOCAL_UPLOAD_DIR / Path(row.s3_key).name).unlink(missing_ok=True)
            except Exception:
                pass
        else:
            client = _client()
            if client is not None:
                try:
                    client.delete_object(Bucket=row.bucket, Key=row.s3_key)
                except Exception:
                    pass
        sess.delete(row)
        return True


def get_file(file_id: str) -> FileAsset | None:
    with get_session() as sess:
        row = sess.get(FileAsset, file_id)
        if row is None:
            return None
        sess.expunge(row)
        return row


def files_for_event(event_id: str, purpose: str | None = None) -> list[FileAsset]:
    with get_session() as sess:
        q = sess.query(FileAsset).filter(FileAsset.event_id == event_id)
        if purpose:
            q = q.filter(FileAsset.purpose == purpose)
        rows = q.order_by(FileAsset.created_at.desc()).all()
        for r in rows:
            sess.expunge(r)
        return rows


def logo_for_org() -> FileAsset | None:
    org_id = current_org_id()
    with get_session() as sess:
        row = (
            sess.query(FileAsset)
            .filter(FileAsset.org_id == org_id, FileAsset.purpose == "logo")
            .order_by(FileAsset.created_at.desc())
            .first()
        )
        if row is not None:
            sess.expunge(row)
        return row
