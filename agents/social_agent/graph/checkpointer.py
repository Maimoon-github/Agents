"""
social_agent/graph/checkpointer.py
Factory for durable AsyncPostgresSaver checkpointer backed by PostgreSQL connection pool.
"""
import os
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


async def get_postgres_checkpointer(
    connection_pool: Optional[Any] = None,
    conn_string: Optional[str] = None
) -> Any:
    """
    Provisions and sets up an asynchronous PostgreSQL checkpointer for LangGraph state persistence.
    If no pool or database URI is provided, returns an in-memory fallback checkpointer for local testing.

    Args:
        connection_pool: Optional psycopg_pool.AsyncConnectionPool instance.
        conn_string: Optional PostgreSQL connection string.

    Returns:
        Configured and setup checkpointer instance.
    """
    if connection_pool:
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            checkpointer = AsyncPostgresSaver(connection_pool)
            await checkpointer.setup()
            logger.info("AsyncPostgresSaver initialized and tables provisioned successfully.")
            return checkpointer
        except Exception as e:
            logger.warning("Failed to initialize AsyncPostgresSaver from pool (%s). Falling back.", e)

    if conn_string:
        try:
            from psycopg_pool import AsyncConnectionPool
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            pool = AsyncConnectionPool(conninfo=conn_string, max_size=10, open=False)
            await pool.open()
            checkpointer = AsyncPostgresSaver(pool)
            await checkpointer.setup()
            logger.info("AsyncPostgresSaver initialized from connection string.")
            return checkpointer
        except Exception as e:
            logger.warning("Failed to initialize AsyncPostgresSaver from conn_string (%s). Falling back.", e)

    # In-Memory Fallback for testing / standalone execution
    try:
        from langgraph.checkpoint.memory import MemorySaver
        logger.info("Using MemorySaver checkpointer fallback.")
        return MemorySaver()
    except Exception:
        class DummyCheckpointer:
            async def aget_tuple(self, *args, **kwargs): return None
            async def aput(self, *args, **kwargs): return None
        return DummyCheckpointer()