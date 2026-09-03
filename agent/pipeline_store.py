"""Pipeline store: pipeline_id -> pipeline, backed by Upstash Redis when configured.

Pipelines are stored as they are generated so that downstream endpoints
(export, improve, fetch) can reference them by id instead of re-invoking the
LLM. Backed by Upstash Redis when UPSTASH_REDIS_REST_URL and
UPSTASH_REDIS_REST_TOKEN are set — share links then work across server
instances and survive restarts. Otherwise it falls back to an in-memory dict
persisted to a local JSON file so links still survive restarts locally.
Bounded to avoid unbounded growth.
"""

import hashlib
import json
import os
import time


PIPELINE_STORE_MAX = 50
PIPELINE_STORE_TTL_SECONDS = 7 * 24 * 3600  # 7 days for remote entries
PIPELINE_STORE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "pipeline_store.json"
)


class PipelineStore:
    """pipeline_id -> pipeline.

    In Redis mode each pipeline lives under ``sf:pipeline:{id}`` with a TTL,
    and a sorted set (``sf:pipeline:created``) tracks insertion order so the
    newest PIPELINE_STORE_MAX entries are kept. In fallback mode an in-memory
    dict is persisted to ``file_path`` on every write.
    """

    def __init__(self, max_size=PIPELINE_STORE_MAX,
                 ttl_seconds=PIPELINE_STORE_TTL_SECONDS,
                 file_path=None, redis_client=None):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        # Resolved at call time so tests can redirect the file via the module
        # constant without re-importing the class.
        self.file_path = file_path or PIPELINE_STORE_FILE
        self._memory: dict = {}
        self._redis = redis_client
        if self._redis is None:
            url = os.environ.get("UPSTASH_REDIS_REST_URL", "")
            token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
            if url and token:
                try:
                    from upstash_redis import Redis
                    self._redis = Redis(url=url, token=token)
                except Exception:
                    # Missing/broken dependency — fall back to the local store.
                    self._redis = None
        if self._redis is None:
            self._load_from_disk()

    @property
    def is_remote(self) -> bool:
        return self._redis is not None

    @property
    def backend(self) -> str:
        """Name of the active storage backend: "redis" or "memory"."""
        return "redis" if self._redis is not None else "memory"

    def count(self):
        """Number of entries currently tracked by the active backend.

        In Redis mode this is the size of the insertion-order sorted set; in
        memory mode the local dict. Returns None when the count can't be
        determined (e.g. Redis unreachable).
        """
        if self._redis is not None:
            try:
                return int(self._redis.zcard("sf:pipeline:created") or 0)
            except Exception:
                return None
        return len(self._memory)

    def ping(self) -> bool:
        """Round-trip connectivity check against the Redis backend."""
        if self._redis is None:
            return False
        try:
            return self._redis.ping() == "PONG"
        except Exception:
            return False

    def get(self, pipeline_id):
        if self._redis is not None:
            raw = self._redis.get(f"sf:pipeline:{pipeline_id}")
            if raw is None:
                return None
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                return None
        return self._memory.get(pipeline_id)

    def store(self, pipeline: dict) -> str:
        """Store a pipeline and return its stable content-hash id."""
        pipeline_json = json.dumps(pipeline, sort_keys=True)
        pipeline_id = "p" + hashlib.sha256(pipeline_json.encode()).hexdigest()[:10]
        if self._redis is not None:
            self._redis.set(f"sf:pipeline:{pipeline_id}", pipeline_json,
                            ex=self.ttl_seconds)
            self._redis.zadd("sf:pipeline:created", {pipeline_id: time.time()})
            # Evict oldest entries beyond the cap (sorted set ranks by score).
            evict = self._redis.zrange("sf:pipeline:created", 0,
                                       -(self.max_size + 1))
            if evict:
                for eid in evict:
                    self._redis.delete(f"sf:pipeline:{eid}")
                self._redis.zrem("sf:pipeline:created", *evict)
        else:
            self._memory[pipeline_id] = pipeline
            # Evict oldest entries (dict preserves insertion order) when over
            # the cap.
            while len(self._memory) > self.max_size:
                self._memory.pop(next(iter(self._memory)))
            self._save_to_disk()
        return pipeline_id

    def clear(self):
        """Clear the local store. In remote mode this only clears the local
        cache — never the shared Redis store, which other instances rely on.
        """
        self._memory.clear()

    def __contains__(self, pipeline_id):
        return self.get(pipeline_id) is not None

    def __getitem__(self, pipeline_id):
        value = self.get(pipeline_id)
        if value is None:
            raise KeyError(pipeline_id)
        return value

    def __len__(self):
        return len(self._memory)

    def values(self):
        return self._memory.values()

    def items(self):
        return self._memory.items()

    # -- local (fallback) persistence ---------------------------------------

    def _load_from_disk(self):
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                if isinstance(stored, dict):
                    self._memory = {k: v for k, v in stored.items()
                                    if isinstance(k, str) and isinstance(v, dict)}
                    while len(self._memory) > self.max_size:
                        self._memory.pop(next(iter(self._memory)))
        except Exception:
            # Corrupt or unreadable file — start empty rather than crash.
            self._memory = {}

    def _save_to_disk(self):
        try:
            tmp = self.file_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._memory, f)
            os.replace(tmp, self.file_path)
        except Exception:
            pass