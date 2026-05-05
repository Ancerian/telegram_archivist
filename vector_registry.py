"""
vector_registry.py — Векторний пошук по реєстру через FAISS (optional).
Якщо faiss/sentence-transformers не встановлені — fallback до текстового пошуку.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class VectorRegistry:
    """Семантичний пошук по реєстру через FAISS."""

    MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    _available = None  # Кеш перевірки доступності

    def __init__(self, registry=None, index_dir: Path = None):
        self.registry = registry
        self.index_dir = index_dir or Path(".")
        self.index = None
        self.model = None
        self.id_to_key = {}
        self._load_or_build()

    @classmethod
    def is_available(cls) -> bool:
        """Перевіряє чи FAISS і sentence-transformers доступні."""
        if cls._available is not None:
            return cls._available
        try:
            import faiss  # noqa: F401
            from sentence_transformers import SentenceTransformer  # noqa: F401
            cls._available = True
        except ImportError:
            cls._available = False
        return cls._available

    def _load_or_build(self):
        """Завантажує або будує FAISS індекс."""
        if not self.is_available():
            logger.info("⚠️ faiss/sentence-transformers не встановлені, використовується текстовий пошук")
            return

        try:
            from sentence_transformers import SentenceTransformer
            import faiss

            self.model = SentenceTransformer(self.MODEL_NAME)
            index_path = self.index_dir / "vector_index.faiss"

            if index_path.exists():
                self.index = faiss.read_index(str(index_path))
                # Завантажити маппінг
                import json
                mapping_path = self.index_dir / "vector_mapping.json"
                if mapping_path.exists():
                    with open(mapping_path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                        self.id_to_key = {int(k): tuple(v) for k, v in raw.items()}
            else:
                self._build_index()
        except Exception as e:
            logger.warning(f"⚠️ Помилка ініціалізації FAISS: {e}")
            self.index = None

    def _build_index(self):
        """Будує індекс з реєстру."""
        if not self.registry or not self.model:
            return

        import faiss
        import numpy as np
        import json

        names = []
        keys = []
        for key, person in self.registry.data.get("people", {}).items():
            text = person.get("canonical_name", key) + " " + " ".join(person.get("aliases", []))
            names.append(text)
            keys.append(("people", key))

        for key, proj in self.registry.data.get("projects", {}).items():
            text = proj.get("canonical_name", key)
            names.append(text)
            keys.append(("projects", key))

        if not names:
            return

        embeddings = self.model.encode(names)
        self.index = faiss.IndexFlatL2(embeddings.shape[1])
        self.index.add(np.array(embeddings, dtype=np.float32))
        self.id_to_key = {i: keys[i] for i in range(len(keys))}

        faiss.write_index(self.index, str(self.index_dir / "vector_index.faiss"))
        with open(self.index_dir / "vector_mapping.json", "w", encoding="utf-8") as f:
            json.dump({str(k): list(v) for k, v in self.id_to_key.items()}, f, ensure_ascii=False)

    def find_relevant(self, batch_text: str, top_k: int = 20) -> list:
        """Знаходить найрелевантніші сутності для батчу."""
        if self.index is None or self.model is None:
            return []
        import numpy as np
        query_vec = self.model.encode([batch_text])
        distances, indices = self.index.search(np.array(query_vec, dtype=np.float32), min(top_k, self.index.ntotal))
        return [self.id_to_key[i] for i in indices[0] if i in self.id_to_key and i >= 0]

    def rebuild(self):
        """Перебудовує індекс після додавання нових сутностей."""
        index_path = self.index_dir / "vector_index.faiss"
        if index_path.exists():
            index_path.unlink(missing_ok=True)
        mapping_path = self.index_dir / "vector_mapping.json"
        if mapping_path.exists():
            mapping_path.unlink(missing_ok=True)
        self._build_index()
