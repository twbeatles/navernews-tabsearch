import logging
import os
from typing import Dict, List, Optional

from core.constants import CONFIG_FILE
from core.config_store import load_config_file, save_config_file_atomic
from core.logging_setup import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

class KeywordGroupManager:
    """키워드 그룹(폴더) 관리"""
    
    def __init__(self, config_file: str = CONFIG_FILE, legacy_file: Optional[str] = None):
        self.config_file = config_file
        self.legacy_file = legacy_file or os.path.join(
            os.path.dirname(os.path.abspath(config_file)),
            "keyword_groups.json",
        )
        self.groups: Dict[str, List[str]] = {}  # {그룹명: [키워드 목록]}
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
            self.groups = {}
    
    def save_groups(self):
        """그룹 설정 저장"""
        try:
            config = load_config_file(self.config_file)
            config["keyword_groups"] = self._normalize_groups(self.groups)
            save_config_file_atomic(self.config_file, config)
        except Exception as e:
            logger.error(f"키워드 그룹 저장 오류: {e}")
    
    def create_group(self, name: str) -> bool:
        """새 그룹 생성"""
        if name in self.groups:
            return False
        self.groups[name] = []
        self.save_groups()
        return True
    
    def delete_group(self, name: str) -> bool:
        """그룹 삭제"""
        if name not in self.groups:
            return False
        del self.groups[name]
        self.save_groups()
        return True
    
    def add_keyword_to_group(self, group: str, keyword: str) -> bool:
        """그룹에 키워드 추가"""
        if group not in self.groups:
            return False
        if keyword not in self.groups[group]:
            self.groups[group].append(keyword)
            self.save_groups()
        return True
    
    def remove_keyword_from_group(self, group: str, keyword: str) -> bool:
        """그룹에서 키워드 제거"""
        if group not in self.groups:
            return False
        if keyword in self.groups[group]:
            self.groups[group].remove(keyword)
            self.save_groups()
        return True
    
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
