"""
social_agent/memory/__init__.py
Public package interface for the memory and Corrective RAG (CRAG) subsystem.
Exposes vector storage, hybrid retrieval with RRF, and thread session management.
"""
from .vector_store import (
    VectorStoreManager,
    RetrievedDocument,
)
from .hybrid_retriever import (
    HybridRetriever,
    RetrievalStatus,
    RetrievalVerdict,
)
from .session_manager import (
    SessionManager,
    SessionContext,
)

__all__ = [
    "VectorStoreManager",
    "RetrievedDocument",
    "HybridRetriever",
    "RetrievalStatus",
    "RetrievalVerdict",
    "SessionManager",
    "SessionContext",
]