"""Relational storage. Each table keeps its foreign keys as columns and the record as JSON."""
from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import JSON, Column, MetaData, String, Table, create_engine, select
from sqlalchemy.pool import StaticPool

T = TypeVar("T", bound=BaseModel)

metadata = MetaData()


def _table(name: str, *keys: str) -> Table:
    columns = [Column("id", String, primary_key=True)]
    columns += [Column(key, String, index=True) for key in keys]
    return Table(name, metadata, *columns, Column("data", JSON, nullable=False))


TABLES = {
    "documents": _table("documents"),
    "spans": _table("spans", "document_id"),
    "analyses": _table("analyses", "document_id", "idempotency_key"),
    "claims": _table("claims", "analysis_id", "document_id"),
    "states": _table("states", "analysis_id", "claim_id"),
    "evidence": _table("evidence", "claim_id", "group_id", "span_id"),
    "calculations": _table("calculations", "claim_id"),
    "updates": _table("updates", "claim_id"),
    "findings": _table("findings", "analysis_id", "claim_id"),
    "reviews": _table("reviews", "finding_id"),
    "manifests": _table("manifests", "analysis_id"),
}


class Store:
    def __init__(self, url: str = "sqlite:///countercheck.db") -> None:
        options = {}
        if url in ("sqlite://", "sqlite:///:memory:"):
            # One shared connection keeps an in-memory database alive across calls.
            options = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
        self.engine = create_engine(url, **options)
        metadata.create_all(self.engine)

    def put(self, table: str, record_id: str, data: BaseModel | dict, **keys: str | None) -> None:
        payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
        t = TABLES[table]
        with self.engine.begin() as conn:
            conn.execute(t.delete().where(t.c.id == record_id))
            conn.execute(t.insert().values(id=record_id, data=payload, **keys))

    def update(self, table: str, record_id: str, data: BaseModel | dict) -> None:
        """Replace the record and leave its key columns as they are."""
        payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
        t = TABLES[table]
        with self.engine.begin() as conn:
            conn.execute(t.update().where(t.c.id == record_id).values(data=payload))

    def get(self, table: str, record_id: str, model: type[T] | None = None) -> T | dict | None:
        t = TABLES[table]
        with self.engine.connect() as conn:
            row = conn.execute(select(t.c.data).where(t.c.id == record_id)).first()
        if row is None:
            return None
        return model.model_validate(row[0]) if model else row[0]

    def find(self, table: str, model: type[T] | None = None, **keys: str) -> list[T] | list[dict]:
        t = TABLES[table]
        query = select(t.c.data)
        for key, value in keys.items():
            query = query.where(t.c[key] == value)
        with self.engine.connect() as conn:
            rows = [row[0] for row in conn.execute(query)]
        return [model.model_validate(row) for row in rows] if model else rows
