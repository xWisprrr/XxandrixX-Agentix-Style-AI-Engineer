from __future__ import annotations

from typing import Dict, List


class Runtime:
    _LANGUAGE_MAP: Dict[str, Dict[str, str]] = {
        "python": {"cmd": "python3", "ext": ".py"},
        "python3": {"cmd": "python3", "ext": ".py"},
        "javascript": {"cmd": "node", "ext": ".js"},
        "js": {"cmd": "node", "ext": ".js"},
        "node": {"cmd": "node", "ext": ".js"},
        "bash": {"cmd": "bash", "ext": ".sh"},
        "shell": {"cmd": "bash", "ext": ".sh"},
        "sh": {"cmd": "bash", "ext": ".sh"},
    }

    def get_command(self, language: str, file_path: str) -> List[str]:
        info = self._LANGUAGE_MAP.get(language.lower())
        if not info:
            raise ValueError(f"Unsupported language: {language}")
        return [info["cmd"], file_path]

    def get_extension(self, language: str) -> str:
        info = self._LANGUAGE_MAP.get(language.lower())
        if not info:
            return ".py"
        return info["ext"]

    def is_supported(self, language: str) -> bool:
        return language.lower() in self._LANGUAGE_MAP
