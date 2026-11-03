"""Stage explicitly selected project uploads for Codex image input.

Asset records must come from the project's trusted asset store, not from the
model or client-supplied metadata. The caller owns and removes staging_dir.
"""

import hashlib
import os
from pathlib import Path
import re
import stat

MAX_IMAGES = 10
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
_ASSET_ID = re.compile(r"A-[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FORMATS = {"image/png": (".png", b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": (".jpg", b"\xff\xd8\xff")}


class ImageSelectionError(ValueError):
    """An upload could not be safely staged; the message contains no paths."""


def stage_codex_images(project_dir, staging_dir, selected_ids, asset_records):
    """Return paths to verified copies of selected PNG/JPEG uploads.

    selected_ids are the user-authorized IDs for this turn. asset_records must
    be project-scoped records obtained from the server's asset database. Other
    selected attachment types are ignored. Fail closed on invalid image records.
    Staged files must remain present until the Codex subprocess exits.
    """
    if not isinstance(selected_ids, (list, tuple)) or len(selected_ids) > MAX_IMAGES:
        raise ImageSelectionError("Invalid attachment selection.")
    if any(not isinstance(i, str) or not _ASSET_ID.fullmatch(i) for i in selected_ids):
        raise ImageSelectionError("Invalid attachment selection.")
    if len(set(selected_ids)) != len(selected_ids):
        raise ImageSelectionError("Duplicate attachment selection.")
    records = {}
    for record in asset_records:
        if not isinstance(record, dict) or record.get("id") in records:
            raise ImageSelectionError("Invalid asset records.")
        records[record.get("id")] = record
    staged = []
    total = 0
    try:
        root_fd = os.open(project_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            upload_fd = os.open("uploads", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd) if selected_ids else None
            try:
                for asset_id in selected_ids:
                    record = records.get(asset_id)
                    if record is None:
                        raise ImageSelectionError("Selected attachment is unavailable.")
                    mime = record.get("mime")
                    if mime not in _FORMATS:
                        if mime in {"application/pdf", "text/plain", "text/markdown"}:
                            continue
                        raise ImageSelectionError("Invalid attachment type.")
                    suffix, magic = _FORMATS[mime]
                    name = asset_id + suffix
                    digest = record.get("sha256")
                    size = record.get("bytes")
                    if (record.get("path") != "uploads/" + name or not isinstance(digest, str)
                            or not _SHA256.fullmatch(digest) or type(size) is not int
                            or not 0 < size <= MAX_IMAGE_BYTES):
                        raise ImageSelectionError("Invalid image metadata.")
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=upload_fd)
                    try:
                        info = os.fstat(fd)
                        if not stat.S_ISREG(info.st_mode) or info.st_size != size:
                            raise ImageSelectionError("Image upload has changed.")
                        with os.fdopen(fd, "rb", closefd=False) as source:
                            data = source.read(MAX_IMAGE_BYTES + 1)
                    finally:
                        os.close(fd)
                    if len(data) != size or not data.startswith(magic) or hashlib.sha256(data).hexdigest() != digest:
                        raise ImageSelectionError("Image upload has changed.")
                    total += size
                    if total > MAX_TOTAL_BYTES:
                        raise ImageSelectionError("Selected images exceed the total size limit.")
                    dest = Path(staging_dir) / name
                    out = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(out, "wb") as target:
                        target.write(data)
                    staged.append(dest)
            finally:
                if upload_fd is not None:
                    os.close(upload_fd)
        finally:
            os.close(root_fd)
        return staged
    except (OSError, ImageSelectionError) as exc:
        for path in staged:
            try:
                path.unlink()
            except OSError:
                pass
        if isinstance(exc, ImageSelectionError):
            raise
        raise ImageSelectionError("Unable to safely stage selected images.") from None
