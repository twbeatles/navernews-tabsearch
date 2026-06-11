import re
from typing import Tuple

class ValidationUtils:
    """입력 검증 유틸리티"""
    
    @staticmethod
    def validate_api_credentials(client_id: str, client_secret: str) -> Tuple[bool, str]:
        """API 자격증명 검증"""
        if not client_id or not client_id.strip():
            return False, "Client ID가 비어있습니다."
        if not client_secret or not client_secret.strip():
            return False, "Client Secret이 비어있습니다."
        if len(client_id.strip()) < 10:
            return False, "Client ID가 너무 짧습니다."
        if len(client_secret.strip()) < 10:
            return False, "Client Secret이 너무 짧습니다."
        return True, ""
    
    @staticmethod
    def sanitize_keyword(keyword: str) -> str:
        """키워드 정제"""
        return keyword.strip()[:100]

    @staticmethod
    def safe_filename_component(value: str, fallback: str = "news", max_length: int = 80) -> str:
        """Return a filesystem-safe filename component for dialog defaults."""
        text = " ".join(str(value or "").strip().split())
        if not text:
            return fallback
        text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)
        text = re.sub(r"_+", "_", text).strip(" ._")
        if not text:
            return fallback
        text = text[: max(1, int(max_length or 1))].rstrip(" ._")
        reserved = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
        if text.upper() in reserved:
            text = f"{text}_"
        return text or fallback
