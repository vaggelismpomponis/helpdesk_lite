"""Config from environment variables, plus the embedding function."""
import hashlib
import math
import os
import re

import psycopg
from neo4j import Driver, GraphDatabase

DIM = int(os.getenv("EMBEDDING_DIM", "1536"))  # text-embedding-3-small = 1536


def pg() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"])


def neo4j_driver() -> Driver:
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]),
    )


def embed(texts: list[str]) -> list[list[float]]:
    if os.getenv("AZURE_OPENAI_API_KEY"):
        from langchain_openai import AzureOpenAIEmbeddings

        # reads AZURE_OPENAI_ENDPOINT and OPENAI_API_VERSION from the environment itself
        return AzureOpenAIEmbeddings(
            azure_deployment=os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"], dimensions=DIM
        ).embed_documents(texts)
    if os.getenv("OPENAI_API_KEY"):
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"), dimensions=DIM
        ).embed_documents(texts)
    # shortcut: hashed bag-of-words (lexical, not semantic) so dev and tests run offline;
    # upgrade by setting AZURE_OPENAI_API_KEY or OPENAI_API_KEY and re-running ingestion.
    return [_hash_embed(t) for t in texts]


def _hash_embed(text: str) -> list[float]:
    v = [0.0] * DIM
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def vec(v: list[float]) -> str:
    """pgvector text literal, cast with ::vector in SQL (avoids the pgvector python package)."""
    return "[" + ",".join(map(str, v)) + "]"
