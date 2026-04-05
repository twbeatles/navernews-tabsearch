import logging
import os
from typing import Dict, List, Optional

from core.constants import CONFIG_FILE
from core.config_store import load_config_file, save_primary_config_file
from core.logging_setup import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


def merge_keyword_groups(
    existing_groups: Dict[str, List[str]],
    incoming_groups: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    """그룹 병합 유틸리티: 기존 순서를 우선 유지하고 신규 키워드를 뒤에 추가."""
    merged: Dict[str, List[str]] = {}

    for group_name, keywords in existing_groups.items():
        merged[group_name] = list(keywords)

    for group_name, incoming_keywords in incoming_groups.items():
        if group_name not in merged:
            merged[group_name] = []
        for keyword in incoming_keywords:
            if keyword not in merged[group_name]:
                merged[group_name].append(keyword)

    return merged


class KeywordGroupManager:
    """키워드 그룹(폴더) 관리"""
    
    def __init__(self, config_file: str = CONFIG_FILE, legacy_file: Optional[str] = None):
        self.config_file = config_file
        self.legacy_file = legacy_file or os.path.join(
            os.path.dirname(os.path.abspath(config_file)),
            "keyword_groups.json",
        )
        self.groups: Dict[str, List[str]] = {}  # {그룹명: [키워드 목록]}
        self.last_error: str = ""
        self.load_groups()

    def _normalize_groups(self, groups: Dict[str, List[str]]) -> Dict[str, List[str]]:
        normalized: Dict[str, List[str]] = {}
        for group_name, raw_keywords in groups.items():
            if not isinstance(group_name, str):
                continue
            cleaned_group_name = group_name.strip()
            if not cleaned_group_name:
                continue

            keywords: List[str] = []
            if isinstance(raw_keywords, list):
                for raw_keyword in raw_keywords:
                    if not isinstance(raw_keyword, str):
                        continue
                    keyword = raw_keyword.strip()
                    if keyword and keyword not in keywords:
                        keywords.append(keyword)
            normalized[cleaned_group_name] = keywords
        return normalized

    def _load_legacy_groups(self) -> Dict[str, List[str]]:
        if not self.legacy_file or self.legacy_file == self.config_file:
            return {}
        if not os.path.exists(self.legacy_file):
            return {}

        try:
            import json

            with open(self.legacy_file, "r", encoding="utf-8") as f:
                raw = json.load(f)

            if isinstance(raw, dict) and "keyword_groups" in raw and isinstance(raw.get("keyword_groups"), dict):
                return self._normalize_groups(raw["keyword_groups"])
            if isinstance(raw, dict):
                return self._normalize_groups(raw)
        except Exception as e:
            logger.error(f"레거시 키워드 그룹 로드 오류: {e}")
        return {}
    
    def load_groups(self):
        """그룹 설정 로드"""
        try:
            config = load_config_file(self.config_file)
            current_groups = self._normalize_groups(config.get("keyword_groups", {}))
            if current_groups:
                self.groups = current_groups
                return

            legacy_groups = self._load_legacy_groups()
            self.groups = legacy_groups
            if legacy_groups:
                logger.info("레거시 키워드 그룹을 config 파일로 마이그레이션합니다.")
                self.save_groups()
        except Exception as e:
            logger.error(f"키워드 그룹 로드 오류: {e}")
            self.last_error = str(e)
            self.groups = {}

    def _persist_groups(self, groups: Dict[str, List[str]]) -> bool:
        normalized_groups = self._normalize_groups(groups)
        try:
            config = load_config_file(self.config_file)
            config["keyword_groups"] = normalized_groups
            save_primary_config_file(self.config_file, config)
            self.groups = normalized_groups
            self.last_error = ""
            return True
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"키워드 그룹 저장 오류: {e}")
            return False

    def replace_groups(self, groups: Dict[str, List[str]]) -> bool:
        """전체 그룹 구성을 저장 가능한 상태로 교체한다."""
        return self._persist_groups(groups)
    
    def save_groups(self) -> bool:
        """그룹 설정 저장"""
        return self._persist_groups(self.groups)

    def merge_groups(self, incoming_groups: Dict[str, List[str]], save: bool = True) -> Dict[str, List[str]]:
        """가져온 그룹과 현재 그룹을 병합한다."""
        normalized_existing = self._normalize_groups(self.groups)
        normalized_incoming = self._normalize_groups(incoming_groups or {})
        merged = merge_keyword_groups(normalized_existing, normalized_incoming)
        if save:
            if self.replace_groups(merged):
                return self.groups
            return normalized_existing

        self.groups = merged
        self.last_error = ""
        return self.groups
    
    def create_group(self, name: str) -> bool:
        """새 그룹 생성"""
        group_name = str(name or "").strip()
        if not group_name:
            self.last_error = "group_name_required"
            return False
        if group_name in self.groups:
            self.last_error = "duplicate_group"
            return False
        candidate = self._normalize_groups(dict(self.groups))
        candidate[group_name] = []
        return self.replace_groups(candidate)
    
    def delete_group(self, name: str) -> bool:
        """그룹 삭제"""
        if name not in self.groups:
            self.last_error = "group_not_found"
            return False
        candidate = self._normalize_groups(dict(self.groups))
        del candidate[name]
        return self.replace_groups(candidate)
    
    def add_keyword_to_group(self, group: str, keyword: str) -> bool:
        """그룹에 키워드 추가"""
        normalized_group = str(group or "").strip()
        normalized_keyword = str(keyword or "").strip()
        if normalized_group not in self.groups:
            self.last_error = "group_not_found"
            return False
        if not normalized_keyword:
            self.last_error = "keyword_required"
            return False
        if normalized_keyword in self.groups[normalized_group]:
            self.last_error = "duplicate_keyword"
            return False
        candidate = self._normalize_groups(dict(self.groups))
        candidate.setdefault(normalized_group, []).append(normalized_keyword)
        return self.replace_groups(candidate)
    
    def remove_keyword_from_group(self, group: str, keyword: str) -> bool:
        """그룹에서 키워드 제거"""
        normalized_group = str(group or "").strip()
        normalized_keyword = str(keyword or "").strip()
        if normalized_group not in self.groups:
            self.last_error = "group_not_found"
            return False
        if normalized_keyword not in self.groups[normalized_group]:
            self.last_error = "keyword_not_found"
            return False
        candidate = self._normalize_groups(dict(self.groups))
        candidate[normalized_group].remove(normalized_keyword)
        return self.replace_groups(candidate)
    
    def get_group_keywords(self, group: str) -> List[str]:
        """그룹의 키워드 목록 반환"""
        return self.groups.get(group, [])
    
    def get_all_groups(self) -> List[str]:
        """모든 그룹명 반환"""
        return list(self.groups.keys())
    
    def get_keyword_group(self, keyword: str) -> Optional[str]:
        """키워드가 속한 그룹 반환"""
        for group, keywords in self.groups.items():
            if keyword in keywords:
                return group
        return None
