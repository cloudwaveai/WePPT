"""Anonymous personal spaces for open-access deployments.

A random owner token in an HttpOnly cookie scopes projects and user templates.
Only its SHA-256 is stored. Items created before personal spaces have no owner
and stay visible to everyone. Without a current owner (token-protected local
use, background workers) every item is accessible, as before.
"""
import contextvars
import hashlib
import re
import secrets

from .core import _now

COOKIE = "weppt_owner"
_current = contextvars.ContextVar("weppt_owner", default=None)


def new_token():
    return secrets.token_urlsafe(32)


def valid(token):
    return isinstance(token, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is not None


def set_current(token):
    return _current.set(hashlib.sha256(token.encode()).hexdigest() if token else None)


# Worker scope for shared projects that have no owner: history-derived
# features see only unowned projects, never a real visitor's space.
_UNOWNED = "\0unowned"


def set_scoped(owner):
    """Scope a background job to its project's owner (or to unowned projects)."""
    return _current.set(owner if owner else _UNOWNED)


def reset(marker):
    _current.reset(marker)


def current():
    return _current.get()


def project_owner(wb, project_id):
    return _owner(wb, "studio_project_owners", "project_id", project_id)


def initialize(wb):
    with wb._connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS studio_project_owners (
            project_id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS studio_template_owners (
            template_id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL);""")


def _owner(wb, table, column, key):
    initialize(wb)
    with wb._connection() as db:
        row = db.execute(f"SELECT owner FROM {table} WHERE {column}=?", (key,)).fetchone()
    return row[0] if row else None


def _claim(wb, table, key):
    owner = current()
    if owner in (None, _UNOWNED):
        return
    initialize(wb)
    with wb.atomic() as db:
        db.execute(f"INSERT OR IGNORE INTO {table} VALUES (?,?,?)", (key, owner, _now()))


def claim_project(wb, project_id):
    _claim(wb, "studio_project_owners", project_id)


def claim_template(wb, template_id):
    _claim(wb, "studio_template_owners", template_id)


def project_visible(wb, project_id):
    owner = current()
    return owner is None or _owner(wb, "studio_project_owners", "project_id", project_id) in (None, owner)


def template_visible(wb, template_id):
    owner = current()
    return owner is None or _owner(wb, "studio_template_owners", "template_id", template_id) in (None, owner)


def owned_project_ids(wb):
    """Projects whose history may feed this context's taste/recommendations.

    None when personal spaces are not in effect (token-protected local use).
    An owner hash scopes to that owner's projects; a job in a shared project
    (_UNOWNED scope) sees only projects that have no owner.
    """
    owner = current()
    if owner is None:
        return None
    initialize(wb)
    with wb._connection() as db:
        owners = dict(db.execute("SELECT project_id, owner FROM studio_project_owners").fetchall())
    if owner == _UNOWNED:
        return {p["projectId"] for p in wb.list_projects() if p["projectId"] not in owners}
    return {pid for pid, value in owners.items() if value == owner}


def list_projects(wb):
    owner = current()
    projects = wb.list_projects()
    if owner is None:
        return projects
    initialize(wb)
    with wb._connection() as db:
        owners = dict(db.execute("SELECT project_id, owner FROM studio_project_owners").fetchall())
    return [p | {"shared": p["projectId"] not in owners} for p in projects
            if owners.get(p["projectId"]) in (None, owner)]
