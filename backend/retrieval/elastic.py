"""Elasticsearch index: BM25 and vector search over preserved passages, fused by rank."""
from __future__ import annotations

from datetime import datetime

from elasticsearch import Elasticsearch, helpers

from backend.config import env
from backend.models import DocumentSnapshot, SourceSpan
from backend.providers.base import LLM, ProviderError
from backend.retrieval.rrf import fuse

INDEX = "countercheck-passages"


class ElasticIndex:
    def __init__(self, llm: LLM | None = None) -> None:
        api_key = env("ELASTICSEARCH_API_KEY")
        self.client = Elasticsearch(env("ELASTICSEARCH_URL"), api_key=api_key)
        self.llm = llm
        properties = {
            "document_id": {"type": "keyword"}, "kind": {"type": "keyword"},
            "text": {"type": "text"}, "admissible_from": {"type": "date"},
        }
        if llm is not None:
            properties["embedding"] = {"type": "dense_vector", "index": True, "similarity": "cosine",
                                       "dims": int(env("OPENAI_EMBED_DIMS", "1536"))}
        if not self.client.indices.exists(index=INDEX):
            self.client.indices.create(index=INDEX, mappings={"dynamic": "strict",
                                                              "properties": properties})

    def _embed(self, texts: list[str]) -> list[list[float]] | None:
        if self.llm is None:
            return None
        try:
            return self.llm.embed(texts)
        except ProviderError:
            return None  # keyword search still works without vectors

    def index(self, document: DocumentSnapshot, spans: list[SourceSpan]) -> None:
        vectors = self._embed([s.text for s in spans])
        actions = []
        for i, span in enumerate(spans):
            source = {"document_id": document.id, "kind": span.kind, "text": span.text,
                      "admissible_from": document.admissible_from}
            if vectors:
                source["embedding"] = vectors[i]
            actions.append({"_index": INDEX, "_id": span.id, "_source": source})
        helpers.bulk(self.client, actions, refresh="wait_for")

    def search(self, query: str, *, size: int, corpus: list[str] | None = None,
               cutoff: datetime | None = None) -> list[str]:
        filters: list[dict] = []
        if corpus is not None:
            filters.append({"terms": {"document_id": corpus}})
        if cutoff is not None:
            # Documents with no known availability time are excluded by this range filter.
            filters.append({"range": {"admissible_from": {"lte": cutoff.isoformat()}}})
        keyword = self.client.search(index=INDEX, size=size, query={
            "bool": {"must": {"match": {"text": query}}, "filter": filters}})
        rankings = [[hit["_id"] for hit in keyword["hits"]["hits"]]]
        vectors = self._embed([query])
        if vectors:
            semantic = self.client.search(index=INDEX, size=size, knn={
                "field": "embedding", "query_vector": vectors[0], "k": size,
                "num_candidates": max(size * 4, 50), "filter": filters})
            rankings.append([hit["_id"] for hit in semantic["hits"]["hits"]])
        return fuse(rankings)[:size]
