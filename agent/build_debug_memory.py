from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_debug_memory_config() -> dict[str, Any]:
    cfg_path = _project_root() / "config.yaml"
    defaults = {
        "enabled": True,
        "sqlite_path": "memory/build_debug/experience.db",
        "max_build_retries": 3,
        "qdrant_collection": "uiforge_build_debug",
        "vector_size": 384,
        "min_similarity_score": 0.5,
    }
    if not cfg_path.exists():
        return defaults
    with cfg_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    merged = {**defaults, **(cfg.get("debug_memory") or {})}
    return merged


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def normalize_build_error(log: str) -> str:
    """去 ANSI 并提取 Vite/Rollup 关键错误段。"""
    text = strip_ansi(log or "").strip()
    if not text:
        return ""

    markers = (
        "error during build",
        "Build failed",
        "✘",
        "ERROR",
        "SyntaxError",
        "TypeError",
        "failed to resolve",
        "Could not resolve",
        "Rollup failed",
    )
    lines = text.splitlines()
    hit_indices: list[int] = []
    for i, line in enumerate(lines):
        lower = line.lower()
        if any(m.lower() in lower for m in markers):
            hit_indices.append(i)
        if re.search(r"\b(src/|\w+\.jsx?:\d+)", line):
            hit_indices.append(i)

    if hit_indices:
        start = max(0, min(hit_indices) - 3)
        end = min(len(lines), max(hit_indices) + 15)
        chunk = "\n".join(lines[start:end]).strip()
        if chunk:
            return chunk[:8000]

    return text[-8000:]


def extract_error_signature(error_text: str) -> str:
    """提取 file:line + message 便于展示。"""
    lines = [ln.strip() for ln in error_text.splitlines() if ln.strip()]
    sig_parts: list[str] = []
    for ln in lines:
        if re.search(r"\.(jsx?|tsx?|css):\d+", ln) or "error" in ln.lower():
            sig_parts.append(ln[:200])
        if len(sig_parts) >= 5:
            break
    if sig_parts:
        return "\n".join(sig_parts)[:1000]
    return (lines[0] if lines else error_text)[:500]


@dataclass
class BuildDebugExperience:
    id: str
    error_text: str
    error_signature: str
    root_cause: str
    pitfalls: str
    fix_experience: str
    score: float = 0.0


class _TextEmbedder:
    """轻量嵌入：优先 sentence-transformers，失败则哈希 TF-IDF 风格兜底。"""

    def __init__(self, model_name: str, vector_size: int):
        self.model_name = model_name
        self.vector_size = vector_size
        self._model = None
        self._backend = "hash"

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            test = self._model.encode("health_check")
            self.vector_size = len(test)
            self._backend = "st"
        except Exception:
            self._model = None
            self._backend = "hash"

    def encode(self, text: str) -> list[float]:
        self._load()
        if self._backend == "st" and self._model is not None:
            vec = self._model.encode(text)
            if hasattr(vec, "tolist"):
                return [float(x) for x in vec.tolist()]
            return [float(x) for x in vec]

        # 确定性哈希向量兜底（维度对齐 config）
        import hashlib

        dim = int(self.vector_size)
        digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).digest()
        out: list[float] = []
        i = 0
        while len(out) < dim:
            chunk = digest[i % len(digest) : (i % len(digest)) + 4]
            if len(chunk) < 4:
                chunk = digest[:4]
            val = int.from_bytes(chunk.ljust(4, b"\0")[:4], "big") / 2**32
            out.append(val * 2 - 1)
            i += 1
        return out[:dim]


class BuildDebugMemoryStore:
    """SQLite 权威存储 + Qdrant 报错向量索引。"""

    def __init__(self, project_root: str | Path | None = None):
        self.root = Path(project_root or _project_root())
        self.cfg = _load_debug_memory_config()
        sqlite_rel = str(self.cfg.get("sqlite_path", "memory/build_debug/experience.db"))
        self.db_path = (self.root / sqlite_rel).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.collection = str(self.cfg.get("qdrant_collection", "uiforge_build_debug"))
        self.vector_size = int(self.cfg.get("vector_size", 384))
        self.min_similarity_score = float(self.cfg.get("min_similarity_score", 0.5))
        self._lock = threading.Lock()
        self._qdrant = None
        self._qdrant_ok = False
        self._embedder: _TextEmbedder | None = None
        self._init_sqlite()
        self._init_qdrant()

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", True))

    def _init_sqlite(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS build_debug_experience (
                    id TEXT PRIMARY KEY,
                    error_text TEXT NOT NULL,
                    error_signature TEXT,
                    root_cause TEXT,
                    pitfalls TEXT,
                    fix_experience TEXT,
                    created_at INTEGER,
                    metadata TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _init_qdrant(self) -> None:
        url = os.getenv("QDRANT_URL", "").strip()
        if not url:
            return
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http.models import Distance, VectorParams

            api_key = os.getenv("QDRANT_API_KEY") or None
            timeout = int(os.getenv("QDRANT_TIMEOUT", "30"))
            client = QdrantClient(url=url, api_key=api_key, timeout=timeout)
            collections = {c.name for c in client.get_collections().collections}
            if self.collection not in collections:
                client.create_collection(
                    collection_name=self.collection,
                    vectors_config=VectorParams(
                        size=self.vector_size,
                        distance=Distance.COSINE,
                    ),
                )
            self._qdrant = client
            self._qdrant_ok = True
        except Exception:
            self._qdrant = None
            self._qdrant_ok = False

    def _get_embedder(self) -> _TextEmbedder:
        if self._embedder is None:
            model_type = os.getenv("EMBED_MODEL_TYPE", "local").strip().lower()
            default_model = (
                "sentence-transformers/all-MiniLM-L6-v2"
                if model_type == "local"
                else "text-embedding-v3"
            )
            model_name = os.getenv("EMBED_MODEL_NAME", default_model).strip()
            hf_cache = os.getenv(
                "HUGGINGFACE_HUB_CACHE",
                "D:/AI-Dormitory/models/huggingface/hub",
            )
            os.environ.setdefault("HUGGINGFACE_HUB_CACHE", hf_cache)
            self._embedder = _TextEmbedder(model_name, self.vector_size)
        return self._embedder

    def _get_by_id(self, memory_id: str) -> BuildDebugExperience | None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM build_debug_experience WHERE id = ?",
                (memory_id,),
            ).fetchone()
            if not row:
                return None
            return BuildDebugExperience(
                id=row["id"],
                error_text=row["error_text"],
                error_signature=row["error_signature"] or "",
                root_cause=row["root_cause"] or "",
                pitfalls=row["pitfalls"] or "",
                fix_experience=row["fix_experience"] or "",
            )
        finally:
            conn.close()

    def count_experience(self) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM build_debug_experience"
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def has_experience(self) -> bool:
        return self.count_experience() > 0

    def clear_all(self) -> int:
        """清空 SQLite 与 Qdrant 中的全部 Debug 经验。"""
        removed = self.count_experience()
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("DELETE FROM build_debug_experience")
                conn.commit()
            finally:
                conn.close()
            if self._qdrant_ok and self._qdrant is not None:
                try:
                    self._qdrant.delete_collection(self.collection)
                except Exception:
                    pass
                self._qdrant = None
                self._qdrant_ok = False
                self._init_qdrant()
        return removed

    def search_similar_errors(
        self,
        error_text: str,
        *,
        limit: int = 3,
    ) -> list[BuildDebugExperience]:
        if not self.enabled or not self.has_experience():
            return []
        normalized = normalize_build_error(error_text)
        if not normalized:
            return []

        if not self._qdrant_ok or self._qdrant is None:
            return self._search_sqlite_fallback(normalized, limit=limit)

        try:
            vec = self._get_embedder().encode(normalized)
            hits = self._qdrant_query(vec, limit=limit)
            results: list[BuildDebugExperience] = []
            for hit in hits:
                mem_id = str(getattr(hit, "id", "") or "")
                exp = self._get_by_id(mem_id)
                if exp:
                    score = float(getattr(hit, "score", 0.0) or 0.0)
                    if score < self.min_similarity_score:
                        continue
                    exp.score = score
                    results.append(exp)
            return results
        except Exception:
            return self._search_sqlite_fallback(normalized, limit=limit)

    def _qdrant_query(self, vec: list[float], *, limit: int) -> list[Any]:
        client = self._qdrant
        if client is None:
            return []
        if hasattr(client, "query_points"):
            resp = client.query_points(
                collection_name=self.collection,
                query=vec,
                limit=limit,
            )
            return list(getattr(resp, "points", []) or [])
        if hasattr(client, "search"):
            return list(
                client.search(
                    collection_name=self.collection,
                    query_vector=vec,
                    limit=limit,
                )
                or []
            )
        return []

    def _search_sqlite_fallback(
        self,
        error_text: str,
        *,
        limit: int,
    ) -> list[BuildDebugExperience]:
        """Qdrant 不可用时按关键词粗略匹配 SQLite。"""
        tokens = [t for t in re.split(r"\W+", error_text.lower()) if len(t) > 3][:12]
        if not tokens:
            return []
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM build_debug_experience ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
            scored: list[tuple[float, BuildDebugExperience]] = []
            for row in rows:
                blob = (row["error_text"] or "").lower()
                score = sum(1 for t in tokens if t in blob) / max(len(tokens), 1)
                if score <= 0:
                    continue
                scored.append(
                    (
                        score,
                        BuildDebugExperience(
                            id=row["id"],
                            error_text=row["error_text"],
                            error_signature=row["error_signature"] or "",
                            root_cause=row["root_cause"] or "",
                            pitfalls=row["pitfalls"] or "",
                            fix_experience=row["fix_experience"] or "",
                            score=score,
                        ),
                    )
                )
            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                item
                for score, item in scored[:limit]
                if score >= self.min_similarity_score
            ]
        finally:
            conn.close()

    def store_lesson(
        self,
        *,
        error_text: str,
        root_cause: str,
        pitfalls: str,
        fix_experience: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        if not self.enabled:
            return ""
        memory_id = str(uuid.uuid4())
        normalized = normalize_build_error(error_text)
        signature = extract_error_signature(normalized)
        created_at = int(time.time())
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO build_debug_experience
                    (id, error_text, error_signature, root_cause, pitfalls,
                     fix_experience, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        normalized,
                        signature,
                        root_cause,
                        pitfalls,
                        fix_experience,
                        created_at,
                        meta_json,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        if self._qdrant_ok and self._qdrant is not None and normalized:
            try:
                vec = self._get_embedder().encode(normalized)
                from qdrant_client.http.models import PointStruct

                self._qdrant.upsert(
                    collection_name=self.collection,
                    points=[
                        PointStruct(
                            id=memory_id,
                            vector=vec,
                            payload={
                                "memory_id": memory_id,
                                "error_signature": signature,
                            },
                        )
                    ],
                )
            except Exception:
                pass

        return memory_id


_store_singleton: BuildDebugMemoryStore | None = None
_store_lock = threading.Lock()


def get_build_debug_memory_store(
    project_root: str | Path | None = None,
) -> BuildDebugMemoryStore:
    global _store_singleton
    if _store_singleton is not None:
        return _store_singleton
    with _store_lock:
        if _store_singleton is None:
            _store_singleton = BuildDebugMemoryStore(project_root)
        return _store_singleton


def reset_build_debug_memory_store() -> None:
    global _store_singleton
    with _store_lock:
        _store_singleton = None


def clear_build_debug_experience(project_root: str | Path | None = None) -> int:
    """清空全局 Debug 经验库并返回删除条数。"""
    store = get_build_debug_memory_store(project_root)
    removed = store.clear_all()
    reset_build_debug_memory_store()
    return removed
