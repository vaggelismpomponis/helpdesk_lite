"""Config from environment variables, plus the embedding function."""
import hashlib
import math
import os
import re

import psycopg
from neo4j import Driver, GraphDatabase

DIM = int(os.getenv("EMBEDDING_DIM", "1536"))  # text-embedding-3-small = 1536


def pg() -> psycopg.Connection:
    url = os.getenv("DATABASE_URL")
    if not url:
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        user = os.getenv("POSTGRES_USER", "postgres")
        pw = os.getenv("POSTGRES_PASSWORD", "postgres_secure_password")
        db = os.getenv("POSTGRES_DB", "helpdesk")
        url = f"postgresql://{user}:{pw}@{host}:{port}/{db}"
    return psycopg.connect(url)


def neo4j_driver() -> Driver:
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "neo4j_secure_password"),
        ),
    )


def embed(texts: list[str]) -> list[list[float]]:
    offline_mode = (
        os.getenv("OFFLINE_MODE", "false").lower() in ("true", "1")
        or os.getenv("EMBEDDING_PROVIDER") == "offline"
    )

    azure_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    if not offline_mode and azure_key and not azure_key.startswith("your_"):
        try:
            from langchain_openai import AzureOpenAIEmbeddings

            # reads AZURE_OPENAI_ENDPOINT and OPENAI_API_VERSION from the environment itself
            return AzureOpenAIEmbeddings(
                azure_deployment=os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"], dimensions=DIM
            ).embed_documents(texts)
        except Exception as exc:
            print(f"[Knowledge Embed] Remote Azure embedding failed ({exc}); falling back to offline hash embeddings.")

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not offline_mode and openai_key and not openai_key.startswith("your_"):
        try:
            from langchain_openai import OpenAIEmbeddings

            return OpenAIEmbeddings(
                model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"), dimensions=DIM
            ).embed_documents(texts)
        except Exception as exc:
            print(f"[Knowledge Embed] Remote OpenAI embedding failed ({exc}); falling back to offline hash embeddings.")

    # Deterministic lexical embeddings for offline testing or placeholder configurations
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
