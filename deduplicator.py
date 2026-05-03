"""
deduplicator.py — Пошук і злиття дублікатів у Obsidian vault.
"""

from pathlib import Path
from difflib import SequenceMatcher

from config import normalize_name
from merger import merge_entity_data
from writer import ObsidianWriter


class VaultDeduplicator:
    """Дедуплікація сутностей у vault та registry."""

    FOLDERS = {
        "People": "people",
        "Projects": "projects",
        "Events": "events",
        "Themes": "themes",
    }

    @staticmethod
    def find_duplicates(vault_path: Path) -> list[list[str]]:
        groups = []
        vault_path = Path(vault_path)

        for folder in VaultDeduplicator.FOLDERS:
            folder_path = vault_path / folder
            if not folder_path.exists():
                continue

            files = sorted(folder_path.glob("*.md"))
            if len(files) < 2:
                continue

            parent = {path: path for path in files}

            def find(path):
                while parent[path] != path:
                    parent[path] = parent[parent[path]]
                    path = parent[path]
                return path

            def union(a, b):
                root_a = find(a)
                root_b = find(b)
                if root_a != root_b:
                    parent[root_b] = root_a

            normalized = {path: normalize_name(path.stem) for path in files}
            for i, left in enumerate(files):
                left_norm = normalized[left]
                if not left_norm:
                    continue
                for right in files[i + 1:]:
                    right_norm = normalized[right]
                    if not right_norm:
                        continue
                    ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
                    if ratio > 0.85:
                        union(left, right)

            by_root = {}
            for path in files:
                by_root.setdefault(find(path), []).append(path)

            for duplicate_group in by_root.values():
                if len(duplicate_group) > 1:
                    groups.append([
                        str(path.relative_to(vault_path))
                        for path in sorted(duplicate_group)
                    ])

        return groups

    @staticmethod
    def merge_duplicates(groups: list, registry) -> int:
        """Зливає групи дублікатів, повертає кількість видалених дубль-файлів."""
        if not groups or registry is None:
            return 0

        vault_path = registry.vault_path
        writer = ObsidianWriter(vault_path, registry=registry)
        merged_files = 0

        for group in groups:
            paths = [vault_path / rel_path for rel_path in group]
            paths = [path for path in paths if path.exists()]
            if len(paths) < 2:
                continue

            main_path = max(paths, key=lambda path: path.stat().st_size)
            entity_type = VaultDeduplicator._entity_type_for_path(main_path)
            if not entity_type:
                continue

            main_rel = main_path.relative_to(vault_path).as_posix()
            main_key = VaultDeduplicator._registry_key_by_file(registry, entity_type, main_rel)
            if not main_key:
                continue

            main_entry = registry.data.get(entity_type, {}).get(main_key, {})
            merged_data = dict(main_entry.get("data") or {})
            aliases = set(main_entry.get("aliases", []))
            sources = set(main_entry.get("sources", []))
            telegram_ids = set(main_entry.get("telegram_ids", []))

            for path in paths:
                rel_path = path.relative_to(vault_path).as_posix()
                key = VaultDeduplicator._registry_key_by_file(registry, entity_type, rel_path)
                if not key or key == main_key:
                    continue

                entry = registry.data.get(entity_type, {}).get(key, {})
                merged_data = merge_entity_data(merged_data, entry.get("data") or {})
                aliases.update(entry.get("aliases", []))
                sources.update(entry.get("sources", []))
                telegram_ids.update(entry.get("telegram_ids", []))
                registry.data.get(entity_type, {}).pop(key, None)

                try:
                    path.unlink()
                    merged_files += 1
                except OSError:
                    pass

            canonical_name = main_entry.get("canonical_name") or main_path.stem
            if entity_type == "themes":
                merged_data["tag"] = canonical_name
            else:
                merged_data["name"] = canonical_name

            main_entry["aliases"] = sorted(aliases)
            main_entry["sources"] = sorted(sources)
            if entity_type == "people":
                main_entry["telegram_ids"] = sorted(telegram_ids)
            main_entry["data"] = merged_data
            main_entry["file"] = main_rel

            VaultDeduplicator._rewrite_entity(writer, entity_type, merged_data)

        return merged_files

    @staticmethod
    def _entity_type_for_path(path: Path) -> str | None:
        return VaultDeduplicator.FOLDERS.get(path.parent.name)

    @staticmethod
    def _registry_key_by_file(registry, entity_type: str, rel_path: str) -> str | None:
        for key, entry in registry.data.get(entity_type, {}).items():
            if entry.get("file") == rel_path:
                return key
        return None

    @staticmethod
    def _rewrite_entity(writer: ObsidianWriter, entity_type: str, data: dict) -> None:
        if entity_type == "people":
            writer._write_person(data, "deduplication", "update")
        elif entity_type == "projects":
            writer._write_project(data, "deduplication", "update")
        elif entity_type == "events":
            writer._write_event(data, "deduplication", "update")
        elif entity_type == "themes":
            writer._write_theme(data, "deduplication", "update")
