"""
health_check.py — Перевірка системи перед запуском аналізу.
"""

import sys
import shutil
from pathlib import Path


class SystemHealthCheck:
    """Перевіряє готовність системи до запуску аналізу."""

    def run_all(self, config: dict = None) -> list:
        """Запускає всі перевірки і повертає список результатів."""
        config = config or {}
        checks = []
        checks.append(self._check_python_version())
        checks.append(self._check_dependencies())
        checks.append(self._check_disk_space())
        checks.append(self._check_ram())
        checks.append(self._check_llm_connection(config))
        checks.append(self._check_vault_writable(config))
        checks.append(self._check_export_valid(config))
        return checks

    def _check_python_version(self) -> dict:
        ok = sys.version_info >= (3, 10)
        return {
            "name": "Python версія",
            "ok": ok,
            "detail": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "critical": True,
        }

    def _check_dependencies(self) -> dict:
        missing = []
        optional_missing = []
        for pkg in ["faster_whisper", "openai", "anthropic", "google.generativeai", "langdetect"]:
            try:
                __import__(pkg)
            except ImportError:
                missing.append(pkg)
        for pkg in ["jinja2", "tiktoken", "psutil"]:
            try:
                __import__(pkg)
            except ImportError:
                optional_missing.append(pkg)

        detail = "Всі встановлені"
        if missing:
            detail = f"Відсутні: {', '.join(missing)}"
        if optional_missing:
            detail += f" | Опціональні: {', '.join(optional_missing)}"

        return {
            "name": "Залежності",
            "ok": not missing,
            "detail": detail,
            "critical": False,
        }

    def _check_disk_space(self) -> dict:
        free_gb = shutil.disk_usage("/").free / 1e9
        ok = free_gb > 2
        return {
            "name": "Місце на диску",
            "ok": ok,
            "detail": f"{free_gb:.1f} GB вільно",
            "critical": False,
        }

    def _check_ram(self) -> dict:
        try:
            import psutil
            free_gb = psutil.virtual_memory().available / 1e9
            ok = free_gb > 4
            return {
                "name": "Оперативна пам'ять",
                "ok": ok,
                "detail": f"{free_gb:.1f} GB вільно",
                "critical": False,
            }
        except ImportError:
            return {
                "name": "Оперативна пам'ять",
                "ok": True,
                "detail": "psutil не встановлено, перевірку пропущено",
                "critical": False,
            }

    def _check_llm_connection(self, config: dict) -> dict:
        provider = config.get("provider", "")
        local_url = config.get("local_url", "http://localhost:1234/v1")

        if provider == "local":
            try:
                import requests
                base_url = local_url.split("/v1")[0]
                r = requests.get(f"{base_url}/api/v0/models", timeout=3)
                if r.status_code == 200:
                    data = r.json().get("data", [])
                    loaded = [m for m in data if m.get("state") == "loaded"]
                    return {
                        "name": "LM Studio",
                        "ok": bool(loaded),
                        "detail": f"{len(loaded)} моделей завантажено" if loaded else "Жодна модель не завантажена",
                        "critical": False,
                    }
                return {"name": "LM Studio", "ok": False, "detail": f"HTTP {r.status_code}", "critical": False}
            except Exception as e:
                return {"name": "LM Studio", "ok": False, "detail": f"Не відповідає: {e}", "critical": False}

        return {"name": "LLM з'єднання", "ok": True, "detail": f"Хмарний провайдер ({provider})", "critical": False}

    def _check_vault_writable(self, config: dict) -> dict:
        vault_path = config.get("vault_path")
        if not vault_path:
            return {"name": "Vault доступний", "ok": True, "detail": "Шлях не вказано", "critical": False}
        vault_path = Path(vault_path)
        try:
            vault_path.mkdir(parents=True, exist_ok=True)
            test_file = vault_path / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            return {"name": "Vault доступний", "ok": True, "detail": str(vault_path), "critical": False}
        except Exception as e:
            return {"name": "Vault доступний", "ok": False, "detail": str(e), "critical": True}

    def _check_export_valid(self, config: dict) -> dict:
        input_path = config.get("input_path")
        if not input_path:
            return {"name": "Експорт валідний", "ok": True, "detail": "Шлях не вказано", "critical": False}
        result_file = Path(input_path) / "result.json"
        if not result_file.exists():
            return {"name": "Експорт валідний", "ok": False, "detail": "result.json не знайдено", "critical": True}
        try:
            import json
            with open(result_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            msg_count = len(data.get("messages", []))
            return {"name": "Експорт валідний", "ok": True, "detail": f"{msg_count} повідомлень", "critical": False}
        except Exception as e:
            return {"name": "Експорт валідний", "ok": False, "detail": f"Помилка JSON: {e}", "critical": True}
