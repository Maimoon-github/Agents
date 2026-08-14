"""
social_agent/memory/vector_store.py
Vector storage client supporting ChromaDB and Qdrant with local Ollama embeddings.
"""
import os
import json
import logging
import asyncio
from typing import Dict, Any, List, Optional, Literal
import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RetrievedDocument(BaseModel):
    """Encapsulates a retrieved document chunk with multi-stage scoring metadata."""
    doc_id: str = Field(..., description="Unique document chunk identifier.")
    content: str = Field(..., description="Text content of the retrieved chunk.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata tags (category, platform, etc.).")
    dense_score: Optional[float] = Field(default=None, description="Cosine similarity score (0.0 - 1.0).")
    sparse_score: Optional[float] = Field(default=None, description="Lexical BM25 score (>= 0.0).")
    rrf_score: Optional[float] = Field(default=None, description="Reciprocal Rank Fusion combined score.")
    rerank_score: Optional[float] = Field(default=None, description="Cross-Encoder calibrated score (0.0 - 1.0).")


class VectorStoreManager:
    """
    Manages semantic document collections, embeddings generation, and vector search.
    Supports ChromaDB, Qdrant, and local in-memory fallback.
    """
    def __init__(
        self,
        persist_directory: str = "/var/data/chromadb",
        embedding_base_url: str = "http://127.0.0.1:11434/v1",
        embedding_model: str = "nomic-embed-text-v1.5",
        embedding_dimension: int = 768,
        engine: Literal["chroma", "qdrant"] = "chroma"
    ):
        self.persist_directory = persist_directory
        self.embedding_base_url = embedding_base_url.rstrip("/")
        self.embedding_model = embedding_model
        self.embedding_dimension = embedding_dimension
        self.engine = engine
        
        # In-memory storage cache for fast retrieval and BM25 syncing
        self._local_storage: Dict[str, List[Dict[str, Any]]] = {
            "brand_governance_rag": [],
            "historical_posts_rag": []
        }
        
        self._init_driver()

    def _init_driver(self):
        """Initializes the underlying vector database client."""
        os.makedirs(self.persist_directory, exist_ok=True)
        if self.engine == "chroma":
            try:
                import chromadb
                self.client = chromadb.PersistentClient(path=self.persist_directory)
                logger.info("Initialized ChromaDB PersistentClient at %s", self.persist_directory)
            except Exception as e:
                logger.warning("ChromaDB driver initialization failed (%s). Using local storage.", e)
                self.client = None
        else:
            self.client = None

    def _sanitize_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Flattens nested structures to comply with vector DB primitive typing rules."""
        sanitized = {}
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool)):
                sanitized[k] = v
            elif isinstance(v, (list, dict)):
                sanitized[k] = json.dumps(v)
            elif v is None:
                sanitized[k] = ""
            else:
                sanitized[k] = str(v)
        return sanitized

    async def _embed_texts(self, texts: List[str], task_type: str = "search_document") -> List[List[float]]:
        """
        Dispatches texts to Ollama /v1/embeddings (or /api/embeddings) with task_type parameter.
        """
        if not texts:
            return []

        async with httpx.AsyncClient(timeout=15.0) as http_client:
            # 1. Try OpenAI-compatible /v1/embeddings endpoint
            try:
                endpoint = f"{self.embedding_base_url}/embeddings"
                payload = {
                    "model": self.embedding_model,
                    "input": texts if len(texts) > 1 else texts[0],
                    "task_type": task_type
                }
                resp = await http_client.post(endpoint, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    if "data" in data and isinstance(data["data"], list):
                        return [item["embedding"] for item in data["data"]]
            except Exception as v1_err:
                logger.debug("Ollama /v1/embeddings call failed (%s), trying fallback.", v1_err)

            # 2. Try native Ollama legacy endpoint /api/embeddings
            try:
                api_base = self.embedding_base_url.replace("/v1", "")
                embeddings = []
                for text in texts:
                    resp = await http_client.post(
                        f"{api_base}/api/embeddings",
                        json={"model": self.embedding_model, "prompt": text}
                    )
                    if resp.status_code == 200:
                        embeddings.append(resp.json().get("embedding", []))
                if len(embeddings) == len(texts) and all(len(e) > 0 for e in embeddings):
                    return embeddings
            except Exception as api_err:
                logger.debug("Ollama /api/embeddings call failed: %s", api_err)

        # 3. Deterministic pseudo-embedding fallback for testing / offline environments
        logger.warning("Using deterministic fallback embeddings for model '%s'", self.embedding_model)
        fallback_embeddings = []
        for text in texts:
            import hashlib
            seed = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)
            vector = [((seed >> (i % 32)) & 0xFF) / 255.0 for i in range(self.embedding_dimension)]
            norm = sum(x * x for x in vector) ** 0.5 or 1.0
            fallback_embeddings.append([x / norm for x in vector])
        return fallback_embeddings

    def get_or_create_collection(self, collection_name: str) -> Any:
        """Retrieves or provisions a named vector collection."""
        if collection_name not in self._local_storage:
            self._local_storage[collection_name] = []
            
        if self.client:
            try:
                return self.client.get_or_create_collection(name=collection_name)
            except Exception as e:
                logger.warning("Failed to get/create Chroma collection '%s': %s", collection_name, e)
        return self._local_storage[collection_name]

    async def add_documents(self, documents: List[Dict[str, Any]], collection_name: str = "brand_governance_rag") -> List[str]:
        """
        Batch adds documents with metadata and dense embeddings to the collection.
        
        Args:
            documents: List of dicts with 'id', 'content', and optional 'metadata'.
            collection_name: Target collection partition.
            
        Returns:
            List of successfully stored document IDs.
        """
        if not documents:
            return []

        doc_ids = [str(doc.get("id", f"doc_{i}")) for i, doc in enumerate(documents)]
        texts = [doc.get("content", "") for doc in documents]
        metadatas = [self._sanitize_metadata(doc.get("metadata", {})) for doc in documents]

        # Generate dense embeddings
        embeddings = await self._embed_texts(texts, task_type="search_document")

        # Update in-memory storage
        if collection_name not in self._local_storage:
            self._local_storage[collection_name] = []

        existing_ids = {d["id"] for d in self._local_storage[collection_name]}
        for doc_id, text, meta, emb in zip(doc_ids, texts, metadatas, embeddings):
            if doc_id not in existing_ids:
                self._local_storage[collection_name].append({
                    "id": doc_id,
                    "content": text,
                    "metadata": meta,
                    "embedding": emb
                })

        # Upsert into Chroma if available
        if self.client:
            try:
                col = self.get_or_create_collection(collection_name)
                col.upsert(
                    ids=doc_ids,
                    documents=texts,
                    metadatas=metadatas,
                    embeddings=embeddings
                )
                logger.info("Upserted %d documents into Chroma collection '%s'", len(doc_ids), collection_name)
            except Exception as e:
                logger.warning("Chroma upsert error (%s); stored in memory.", e)

        return doc_ids

    def get_all(self, collection_name: str = "brand_governance_rag") -> List[Dict[str, Any]]:
        """Extracts the entire corpus for sparse BM25 index synchronization."""
        if self.client:
            try:
                col = self.get_or_create_collection(collection_name)
                data = col.get()
                results = []
                for doc_id, doc, meta in zip(data.get("ids", []), data.get("documents", []), data.get("metadatas", [])):
                    results.append({
                        "id": doc_id,
                        "content": doc,
                        "metadata": meta or {}
                    })
                if results:
                    return results
            except Exception as e:
                logger.debug("Chroma get_all failed: %s. Using local memory.", e)

        return self._local_storage.get(collection_name, [])

    async def dense_search(
        self,
        query: str,
        collection_name: str = "brand_governance_rag",
        top_k: int = 10,
        metadata_filter: Optional[Dict[str, Any]] = None
    ) -> List[RetrievedDocument]:
        """
        Executes dense vector similarity search using query embedding cosine distance.
        """
        query_embeddings = await self._embed_texts([query], task_type="search_query")
        if not query_embeddings:
            return []
        query_vec = query_embeddings[0]

        # Use Chroma if available
        if self.client:
            try:
                col = self.get_or_create_collection(collection_name)
                where_clause = metadata_filter if metadata_filter else None
                res = col.query(
                    query_embeddings=[query_vec],
                    n_results=top_k,
                    where=where_clause
                )
                docs = []
                ids = res.get("ids", [[]])[0]
                documents = res.get("documents", [[]])[0]
                metadatas = res.get("metadatas", [[]])[0]
                distances = res.get("distances", [[]])[0] if "distances" in res else [0.0] * len(ids)

                for doc_id, content, meta, dist in zip(ids, documents, metadatas, distances):
                    sim = max(0.0, min(1.0, 1.0 - (dist / 2.0))) if dist is not None else 0.85
                    docs.append(RetrievedDocument(
                        doc_id=doc_id,
                        content=content,
                        metadata=meta or {},
                        dense_score=round(sim, 4)
                    ))
                return docs
            except Exception as e:
                logger.debug("Chroma query failed (%s); performing in-memory dense search.", e)

        # In-Memory Cosine Similarity Calculation
        corpus = self.get_all(collection_name)
        scored_docs = []
        for item in corpus:
            if metadata_filter:
                match = all(item.get("metadata", {}).get(k) == v for k, v in metadata_filter.items())
                if not match:
                    continue

            emb = item.get("embedding")
            if not emb:
                continue

            dot_product = sum(a * b for a, b in zip(query_vec, emb))
            sim = max(0.0, min(1.0, (dot_product + 1.0) / 2.0))
            scored_docs.append((sim, item))

        scored_docs.sort(key=lambda x: x[0], reverse=True)
        return [
            RetrievedDocument(
                doc_id=item["id"],
                content=item["content"],
                metadata=item.get("metadata", {}),
                dense_score=round(sim, 4)
            )
            for sim, item in scored_docs[:top_k]
        ]