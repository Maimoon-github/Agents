"""
social_agent/memory/hybrid_retriever.py
Hybrid retrieval engine combining BM25, dense vector search, Reciprocal Rank Fusion,
and Cross-Encoder reranking for Corrective RAG (CRAG).
"""
import re
import math
import logging
import asyncio
from enum import Enum
from typing import Dict, Any, List, Optional
import httpx
from pydantic import BaseModel, Field

from .vector_store import VectorStoreManager, RetrievedDocument

logger = logging.getLogger(__name__)


class RetrievalStatus(str, Enum):
    """Corrective RAG (CRAG) routing classification verdict."""
    CORRECT = "CORRECT"
    AMBIGUOUS = "AMBIGUOUS"
    INCORRECT = "INCORRECT"


class RetrievalVerdict(BaseModel):
    """Encapsulates the final evaluation verdict and ranked document set."""
    status: RetrievalStatus = Field(..., description="CRAG evaluation status.")
    top_score: float = Field(..., description="Highest cross-encoder relevance score.")
    documents: List[RetrievedDocument] = Field(default_factory=list, description="Ranked retrieved documents.")
    fallback_required: bool = Field(default=False, description="True if web search fallback is triggered.")
    factual_strips: Optional[List[str]] = Field(default=None, description="Decomposed sentence strips for AMBIGUOUS tier.")


class SimpleBM25:
    """Lightweight in-memory BM25 implementation when rank_bm25 is unavailable."""
    def __init__(self, corpus: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus = corpus
        self.corpus_size = len(corpus)
        self.doc_lens = [len(doc) for doc in corpus]
        self.avgdl = sum(self.doc_lens) / self.corpus_size if self.corpus_size > 0 else 1.0
        self.doc_freqs: List[Dict[str, int]] = []
        self.idf: Dict[str, float] = {}
        self._calc_idf()

    def _calc_idf(self):
        df_counts: Dict[str, int] = {}
        for doc in self.corpus:
            frequencies: Dict[str, int] = {}
            for word in doc:
                frequencies[word] = frequencies.get(word, 0) + 1
            self.doc_freqs.append(frequencies)
            for word in frequencies:
                df_counts[word] = df_counts.get(word, 0) + 1

        for word, freq in df_counts.items():
            self.idf[word] = math.log((self.corpus_size - freq + 0.5) / (freq + 0.5) + 1.0)

    def get_scores(self, query: List[str]) -> List[float]:
        scores = [0.0] * self.corpus_size
        for q in query:
            if q not in self.idf:
                continue
            q_idf = self.idf[q]
            for i, doc_freq in enumerate(self.doc_freqs):
                freq = doc_freq.get(q, 0)
                if freq > 0:
                    denom = freq + self.k1 * (1 - self.b + self.b * (self.doc_lens[i] / self.avgdl))
                    scores[i] += q_idf * (freq * (self.k1 + 1)) / denom
        return scores


class HybridRetriever:
    """
    Orchestrates dense + sparse search, Reciprocal Rank Fusion (RRF),
    Cross-Encoder neural reranking, and CRAG threshold classification.
    """
    def __init__(
        self,
        vector_store: VectorStoreManager,
        reranker_base_url: str = "http://127.0.0.1:11434/v1",
        reranker_model: str = "bge-reranker-large",
        rrf_k: int = 60,
        w_dense: float = 0.5,
        w_sparse: float = 0.5
    ):
        self.vector_store = vector_store
        self.reranker_base_url = reranker_base_url.rstrip("/")
        self.reranker_model = reranker_model
        self.rrf_k = rrf_k
        self.w_dense = w_dense
        self.w_sparse = w_sparse
        
        self._bm25_index: Optional[Any] = None
        self._bm25_corpus_docs: List[Dict[str, Any]] = []

    def _tokenize(self, text: str) -> List[str]:
        """Extracts lower-case alphanumeric tokens."""
        return re.findall(r"\w+", text.lower())

    def index_sparse_corpus(self, corpus_documents: Optional[List[Dict[str, Any]]] = None) -> None:
        """
        Builds or updates the sparse BM25 index from vector store documents.
        """
        docs = corpus_documents if corpus_documents is not None else self.vector_store.get_all()
        if not docs:
            logger.debug("Sparse corpus index is empty.")
            return

        self._bm25_corpus_docs = docs
        tokenized_corpus = [self._tokenize(doc.get("content", "")) for doc in docs]

        try:
            from rank_bm25 import BM25Okapi
            self._bm25_index = BM25Okapi(tokenized_corpus)
            logger.info("Initialized BM25Okapi with %d documents.", len(docs))
        except ImportError:
            self._bm25_index = SimpleBM25(tokenized_corpus)
            logger.info("Initialized fallback SimpleBM25 with %d documents.", len(docs))

    async def _sparse_search(self, query: str, top_k: int = 15, metadata_filter: Optional[Dict[str, Any]] = None) -> List[RetrievedDocument]:
        """Executes BM25 search over the indexed sparse corpus."""
        if not self._bm25_index or not self._bm25_corpus_docs:
            self.index_sparse_corpus()
            if not self._bm25_index:
                return []

        q_tokens = self._tokenize(query)
        if not q_tokens:
            return []

        scores = self._bm25_index.get_scores(q_tokens)
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

        results = []
        for idx in ranked_indices:
            score = scores[idx]
            if score <= 0.0:
                continue

            doc = self._bm25_corpus_docs[idx]
            if metadata_filter:
                meta = doc.get("metadata", {})
                if not all(meta.get(k) == v for k, v in metadata_filter.items()):
                    continue

            results.append(RetrievedDocument(
                doc_id=str(doc.get("id", f"doc_{idx}")),
                content=doc.get("content", ""),
                metadata=doc.get("metadata", {}),
                sparse_score=round(float(score), 4)
            ))
            if len(results) >= top_k:
                break

        return results

    def _reciprocal_rank_fusion(
        self,
        dense_docs: List[RetrievedDocument],
        sparse_docs: List[RetrievedDocument],
        top_k: int = 10
    ) -> List[RetrievedDocument]:
        """
        Fuses dense and sparse result lists using Reciprocal Rank Fusion (RRF).
        Formula: RRF(d) = w_dense / (k + rank_dense) + w_sparse / (k + rank_sparse)
        """
        rrf_scores: Dict[str, float] = {}
        doc_map: Dict[str, RetrievedDocument] = {}

        # Process Dense Ranks
        for rank, doc in enumerate(dense_docs, start=1):
            doc_map[doc.doc_id] = doc
            rrf_scores[doc.doc_id] = rrf_scores.get(doc.doc_id, 0.0) + (self.w_dense / (self.rrf_k + rank))

        # Process Sparse Ranks
        for rank, doc in enumerate(sparse_docs, start=1):
            if doc.doc_id in doc_map:
                doc_map[doc.doc_id].sparse_score = doc.sparse_score
            else:
                doc_map[doc.doc_id] = doc
            rrf_scores[doc.doc_id] = rrf_scores.get(doc.doc_id, 0.0) + (self.w_sparse / (self.rrf_k + rank))

        # Sort by RRF score descending
        sorted_doc_ids = sorted(rrf_scores.keys(), key=lambda did: rrf_scores[did], reverse=True)
        fused_docs = []
        for did in sorted_doc_ids[:top_k]:
            doc = doc_map[did]
            doc.rrf_score = round(rrf_scores[did], 6)
            fused_docs.append(doc)

        return fused_docs

    async def _rerank(self, query: str, documents: List[RetrievedDocument]) -> List[RetrievedDocument]:
        """
        Reranks documents using Cross-Encoder endpoint with 3.0s timeout and RRF fallback.
        """
        if not documents:
            return []

        # 1. Dispatch to local Cross-Encoder / Reranker API
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                endpoint = f"{self.reranker_base_url}/rerank"
                payload = {
                    "model": self.reranker_model,
                    "query": query,
                    "documents": [doc.content for doc in documents],
                    "top_n": len(documents)
                }
                resp = await client.post(endpoint, json=payload)
                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    for item in results:
                        idx = item.get("index", 0)
                        score = float(item.get("relevance_score", 0.8))
                        if idx < len(documents):
                            documents[idx].rerank_score = round(score, 4)
                    documents.sort(key=lambda d: d.rerank_score or 0.0, reverse=True)
                    return documents
        except Exception as e:
            logger.debug("Reranker endpoint timed out or unavailable (%s). Falling back to calibrated score.", e)

        # 2. Fallback: Calibrate score based on available dense or sparse signals
        for doc in documents:
            score = doc.dense_score if doc.dense_score is not None else 0.75
            if doc.sparse_score and doc.sparse_score > 0:
                score = min(1.0, score + 0.08)
            doc.rerank_score = round(score, 4)

        documents.sort(key=lambda d: d.rerank_score or 0.0, reverse=True)
        return documents

    def decompose_and_recompose(self, documents: List[RetrievedDocument], query: str) -> List[str]:
        """
        Decompose-then-recompose algorithm: splits candidate documents into granular
        knowledge strips (sentences) and retains only high-relevance factual segments.
        """
        query_words = set(self._tokenize(query))
        knowledge_strips: List[str] = []

        for doc in documents:
            sentences = re.split(r'(?<=[.!?])\s+', doc.content)
            for s in sentences:
                clean_s = s.strip()
                if len(clean_s) < 12:
                    continue

                sentence_words = set(self._tokenize(clean_s))
                overlap = query_words.intersection(sentence_words)
                
                if overlap or (doc.rerank_score and doc.rerank_score >= 0.75):
                    if clean_s not in knowledge_strips:
                        knowledge_strips.append(clean_s)

        return knowledge_strips[:5]

    async def retrieve_and_evaluate(
        self,
        query: str,
        collection_name: str = "brand_governance_rag",
        top_k: int = 5,
        tau_low: float = 0.60,
        tau_high: float = 0.85,
        metadata_filter: Optional[Dict[str, Any]] = None
    ) -> RetrievalVerdict:
        """
        Executes end-to-end CRAG retrieval:
        1. Parallel Dense & Sparse search
        2. Reciprocal Rank Fusion (RRF)
        3. Cross-Encoder reranking
        4. Dual-threshold evaluation (CORRECT / AMBIGUOUS / INCORRECT)
        """
        dense_task = self.vector_store.dense_search(
            query=query,
            collection_name=collection_name,
            top_k=top_k * 3,
            metadata_filter=metadata_filter
        )
        sparse_task = self._sparse_search(
            query=query,
            top_k=top_k * 3,
            metadata_filter=metadata_filter
        )

        dense_results, sparse_results = await asyncio.gather(dense_task, sparse_task, return_exceptions=True)
        
        dense_docs = dense_results if isinstance(dense_results, list) else []
        sparse_docs = sparse_results if isinstance(sparse_results, list) else []

        # RRF Fusion
        fused_docs = self._reciprocal_rank_fusion(dense_docs, sparse_docs, top_k=top_k * 2)

        # Cross-Encoder Reranking
        ranked_docs = await self._rerank(query, fused_docs)
        final_docs = ranked_docs[:top_k]

        top_score = final_docs[0].rerank_score if final_docs and final_docs[0].rerank_score is not None else 0.0

        # CRAG 3-Tier Classification
        if top_score >= tau_high:
            status = RetrievalStatus.CORRECT
            fallback_required = False
            factual_strips = None
        elif tau_low <= top_score < tau_high:
            status = RetrievalStatus.AMBIGUOUS
            fallback_required = True
            factual_strips = self.decompose_and_recompose(final_docs, query)
        else:
            status = RetrievalStatus.INCORRECT
            fallback_required = True
            factual_strips = None

        return RetrievalVerdict(
            status=status,
            top_score=top_score,
            documents=final_docs,
            fallback_required=fallback_required,
            factual_strips=factual_strips
        )