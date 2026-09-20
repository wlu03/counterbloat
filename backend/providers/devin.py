"""Devin adapter: one session with a required structured output, through the v3 API."""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from backend.config import env
from backend.providers.base import ProviderError

API = "https://api.devin.ai/v3/organizations"
POLL_FAILURES_ALLOWED = 5  # consecutive failed status requests before a session is given up


@dataclass
class Session:
    output: dict | None  # the structured output, or None when the session produced none
    ended: str           # why the wait ended: the last status and detail, or "timed out"
    url: str | None
    acus: float | None   # as the API reported it when the wait ended
    seconds: float


def inlined(schema: dict) -> dict:
    """Devin wants a self-contained schema, so each $ref is replaced by what it points to."""
    definitions = schema.get("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(definitions[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        return [resolve(v) for v in node] if isinstance(node, list) else node
    return resolve(schema)


def run_session(prompt: str, schema: dict, title: str, max_acu: int, timeout_s: int,
                client: httpx.Client | None = None, poll_s: float = 15, sleep=time.sleep) -> Session:
    """Start one paid session, wait for it, and return what it produced.

    A ProviderError means the session could not be started or read. A session that ran and gave no
    output is returned with output None, because that is a result and not an outage.
    """
    key, org = env("DEVIN_API_KEY"), env("DEVIN_ORG_ID")
    if not (key and org):
        raise ProviderError("DEVIN_API_KEY and DEVIN_ORG_ID must be set")
    client = client or httpx.Client(timeout=60)
    headers = {"Authorization": f"Bearer {key}"}
    body = {"prompt": prompt, "title": title, "tags": ["countercheck"],
            "structured_output_required": True, "max_acu_limit": max_acu,
            "structured_output_schema": inlined(schema),
            # The session may run code from a source that is not trusted, so it is given none of
            # the organisation's stored secrets and none of its knowledge.
            "secret_ids": [], "knowledge_ids": []}
    started = time.monotonic()
    try:
        # Not retried: a second request could start a second paid session.
        created = client.post(f"{API}/{org}/sessions", json=body, headers=headers)
        created.raise_for_status()
        session_id = created.json()["session_id"]
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise ProviderError(f"devin session could not be created: {exc}") from exc
    session: dict = {"status": "new"}
    failures, timed_out = 0, False
    while True:
        try:
            answer = client.get(f"{API}/{org}/sessions/{session_id}", headers=headers)
            answer.raise_for_status()
            session, failures = answer.json(), 0
        except (httpx.HTTPError, ValueError) as exc:
            # One failed status request does not end a paid session. Several in a row do.
            failures += 1
            if failures > POLL_FAILURES_ALLOWED:
                raise ProviderError(f"devin session {session_id} could not be read: {exc}") from exc
        # A running session with no detail yet has only just started, so it is still waited for.
        waiting = failures > 0 or session["status"] in ("new", "claimed", "resuming") or (
            session["status"] == "running" and session.get("status_detail") in (None, "working"))
        if not waiting:
            break
        if time.monotonic() - started > timeout_s:
            timed_out = True
            try:  # stop the session, so that it does not go on spending up to its ACU limit
                client.delete(f"{API}/{org}/sessions/{session_id}", headers=headers)
            except httpx.HTTPError:
                pass
            break
        sleep(poll_s)
    ended = f"timed out after {timeout_s} s" if timed_out else \
        f"{session['status']} {session.get('status_detail')}"
    return Session(output=session.get("structured_output") or None, ended=f"session {session_id} {ended}",
                   url=session.get("url"), acus=session.get("acus_consumed"),
                   seconds=round(time.monotonic() - started, 1))
