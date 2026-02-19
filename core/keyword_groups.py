import json
import logging
import os
from typing import Dict, List, Optional

from core.constants import CONFIG_FILE
from core.logging_setup import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

class KeywordGroupManager:
    """키워드 그룹(폴더) 관리"""
    
    def __init__(self, config_file: str = CONFIG_FILE):
        self.config_file = config_file
        self.groups: Dict[str, List[str]] = {}  # {그룹명: [키워드 목록]}
        self.load_groups()
    
    def load_groups(self):
        """그룹 설정 로드"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.groups = config.get('keyword_groups', {})
        except Exception as e:
            logger.error(f"키워드 그룹 로드 오류: {e}")
            self.groups = {}
    
    def save_groups(self):
        """그룹 설정 저장"""
        try:
            config = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            
            config['keyword_groups'] = self.groups
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
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
