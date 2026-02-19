import datetime
import hashlib
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from queue import Queue
from typing import Any, Dict, List, Optional, Tuple

from core.logging_setup import configure_logging
from core.text_utils import RE_WHITESPACE, parse_date_to_ts, perf_timer

configure_logging()
logger = logging.getLogger(__name__)

class DatabaseManager:
    """스레드 안전한 데이터베이스 매니저 (연결 풀 사용) - 디버깅 버전"""
    
    def __init__(self, db_file: str, max_connections: int = 10):
        self.db_file = db_file
        self.max_connections = max_connections
        self.connection_pool = Queue(maxsize=max_connections)
        self._lock = threading.Lock()  # 추가: 스레드 안전성
        self._active_connections = 0   # 추가: 활성 연결 추적
        self._closed = False  # 추가: 종료 상태 추적
        self._emergency_connections = set()  # 추가: 비상 연결 추적
        
        # DB 무결성 검사 및 복구
        if os.path.exists(self.db_file):
            if not self._check_integrity():
                logger.error("데이터베이스 손상 감지. 복구를 시도합니다.")
                self._recover_database()
        
        self.init_db()
        
        for _ in range(max_connections):
            conn = self._create_connection()
            self.connection_pool.put(conn)
    
    def _create_connection(self):
        """새 DB 연결 생성"""
        conn = sqlite3.connect(self.db_file, timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA busy_timeout=30000")  # 추가: 30초 busy timeout
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_connection(self, timeout: float = 10.0):
        """연결 풀에서 연결 가져오기 (타임아웃 추가)"""
        if self._closed:
            raise RuntimeError("DatabaseManager is closed")
        try:
            conn = self.connection_pool.get(timeout=timeout)
            with self._lock:
                self._active_connections += 1
            return conn
        except Exception as e:
            logger.warning(f"DB 연결 획득 실패 (timeout={timeout}s): {e}")
            logger.warning(f"활성 연결 수: {self._active_connections}/{self.max_connections}")
            # 비상 연결 생성 (풀에 반환되지 않음)
            conn = self._create_connection()
            with self._lock:
                self._emergency_connections.add(id(conn))
            return conn
    
    def return_connection(self, conn):
        """연결 풀에 연결 반환 - 비상 연결 처리 개선"""
        if conn is None:
            return
        
        conn_id = id(conn)
        
        # 비상 연결이면 풀에 반환하지 않고 닫기
        with self._lock:
            if conn_id in self._emergency_connections:
                self._emergency_connections.discard(conn_id)
                try:
                    conn.close()
                    logger.debug("비상 연결 정리됨")
                except sqlite3.Error:
                    pass
                return
        
        if self._closed:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            return
        try:
            with self._lock:
                self._active_connections = max(0, self._active_connections - 1)
            # 풀이 가득 찼으면 연결 닫기
            if self.connection_pool.full():
                conn.close()
            else:
                self.connection_pool.put_nowait(conn)
        except Exception as e:
            logger.warning(f"DB 연결 반환 실패: {e}")
            try:
                conn.close()
            except sqlite3.Error:
                pass
    def _check_integrity(self) -> bool:
        """데이터베이스 무결성 검사"""
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            conn.close()
            if result and result[0] == "ok":
                return True
            return False
        except Exception as e:
            logger.error(f"DB 무결성 검사 실패: {e}")
            return False

    def _recover_database(self):
        """손상된 데이터베이스 백업 및 재생성"""
        try:
            # 기존 연결 풀 닫기 (이 시점엔 아직 생성 안됐지만 혹시 모르니)
            
            # 파일 백업
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{self.db_file}.corrupt_{timestamp}"
            
            if os.path.exists(self.db_file):
                try:
                    os.rename(self.db_file, backup_name)
                    logger.info(f"손상된 DB 백업 완료: {backup_name}")
                except OSError:
                    # 파일이 잠겨있거나 사용 중일 경우 복사 시도
                    import shutil
                    shutil.copy2(self.db_file, backup_name)
                    os.remove(self.db_file)
                    logger.info(f"손상된 DB 복사 및 삭제 완료: {backup_name}")
            
        except Exception as e:
            logger.critical(f"DB 복구 실패: {e}")
            # 최후의 수단: 파일명 변경 시도 (충돌 회피)
            
    def init_db(self):
        """데이터베이스 초기화"""
        conn = sqlite3.connect(self.db_file)
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS news (
                    link TEXT PRIMARY KEY,
                    keyword TEXT,
                    title TEXT,
                    description TEXT,
                    pubDate TEXT,
                    publisher TEXT,
                    is_read INTEGER DEFAULT 0,
                    is_bookmarked INTEGER DEFAULT 0,
                    pubDate_ts REAL,
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    notes TEXT,
                    title_hash TEXT,
                    is_duplicate INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS news_keywords (
                    link TEXT NOT NULL,
                    keyword TEXT NOT NULL,
                    is_duplicate INTEGER DEFAULT 0,
                    PRIMARY KEY (link, keyword),
                    FOREIGN KEY (link) REFERENCES news(link) ON DELETE CASCADE
                )
                """
            )

            columns_added = False
            try:
                conn.execute("ALTER TABLE news ADD COLUMN pubDate_ts REAL")
                logger.info("pubDate_ts 컬럼 추가됨")
            except sqlite3.OperationalError:
                pass

            for col, dtype in [
                ("publisher", "TEXT"),
                ("is_read", "INTEGER DEFAULT 0"),
                ("is_bookmarked", "INTEGER DEFAULT 0"),
                ("created_at", "REAL DEFAULT (strftime('%s', 'now'))"),
                ("notes", "TEXT"),
                ("title_hash", "TEXT"),
                ("is_duplicate", "INTEGER DEFAULT 0"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE news ADD COLUMN {col} {dtype}")
                    logger.info(f"{col} 컬럼 추가됨 (마이그레이션)")
                    if col == "title_hash":
                        columns_added = True
                except sqlite3.OperationalError:
                    pass

            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_keyword ON news(keyword)",
                "CREATE INDEX IF NOT EXISTS idx_bookmarked ON news(is_bookmarked)",
                "CREATE INDEX IF NOT EXISTS idx_ts ON news(pubDate_ts)",
                "CREATE INDEX IF NOT EXISTS idx_read ON news(is_read)",
                "CREATE INDEX IF NOT EXISTS idx_read_ts ON news(is_read, pubDate_ts DESC)",
                "CREATE INDEX IF NOT EXISTS idx_title_hash ON news(title_hash)",
                "CREATE INDEX IF NOT EXISTS idx_duplicate ON news(is_duplicate)",
                "CREATE INDEX IF NOT EXISTS idx_keyword_read ON news(keyword, is_read)",
                "CREATE INDEX IF NOT EXISTS idx_keyword_ts ON news(keyword, pubDate_ts DESC)",
                "CREATE INDEX IF NOT EXISTS idx_keyword_dup ON news(keyword, is_duplicate)",
                "CREATE INDEX IF NOT EXISTS idx_bookmarked_ts ON news(is_bookmarked, pubDate_ts DESC)",
                "CREATE INDEX IF NOT EXISTS idx_nk_keyword ON news_keywords(keyword)",
                "CREATE INDEX IF NOT EXISTS idx_nk_link ON news_keywords(link)",
                "CREATE INDEX IF NOT EXISTS idx_nk_keyword_link ON news_keywords(keyword, link)",
                "CREATE INDEX IF NOT EXISTS idx_nk_keyword_dup ON news_keywords(keyword, is_duplicate)",
            ]
            for idx in indexes:
                try:
                    conn.execute(idx)
                except sqlite3.OperationalError as e:
                    logger.debug(f"Index creation skipped: {e}")

            if columns_added:
                cursor = conn.execute("SELECT link, title FROM news WHERE title_hash IS NULL LIMIT 1000")
                rows = cursor.fetchall()
                if rows:
                    logger.info(f"기존 데이터 마이그레이션 중... ({len(rows)}개)")
                    for link, title in rows:
                        if title:
                            title_hash = self._calculate_title_hash(title)
                            conn.execute("UPDATE news SET title_hash = ? WHERE link = ?", (title_hash, link))
                    logger.info("마이그레이션 완료")

            cursor = conn.execute("SELECT link, pubDate FROM news WHERE pubDate_ts IS NULL LIMIT 5000")
            rows = cursor.fetchall()
            if rows:
                logger.info(f"pubDate_ts 데이터 보정 중... ({len(rows)}개)")
                updates = []
                for link, pub_date in rows:
                    updates.append((parse_date_to_ts(pub_date), link))
                if updates:
                    conn.executemany("UPDATE news SET pubDate_ts = ? WHERE link = ?", updates)
                logger.info("pubDate_ts 데이터 보정 완료")

            conn.execute(
                """
                INSERT OR IGNORE INTO news_keywords (link, keyword, is_duplicate)
                SELECT link, keyword, COALESCE(is_duplicate, 0)
                FROM news
                WHERE keyword IS NOT NULL AND keyword != ''
                """
            )

        conn.close()

    def _calculate_title_hash(self, title: str) -> str:
        """제목의 해시 계산 (중복 감지용) - 프리컴파일된 정규식 사용"""
        normalized = RE_WHITESPACE.sub('', title.lower())
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def upsert_news(self, items: List[Dict[str, Any]], keyword: str) -> Tuple[int, int]:
        """뉴스 삽입 및 중복 감지 (배치 처리 최적화)"""
        if not items:
            return 0, 0

        conn = self.get_connection()
        added_count = 0
        duplicate_count = 0

        try:
            with perf_timer("db.upsert_news", f"kw={keyword}|items={len(items)}"):
                prepared_items: List[Dict[str, Any]] = []
                hashes: List[str] = []

                for item in items:
                    pub_date = item.get("pubDate", "")
                    title = item.get("title", "")
                    title_hash = self._calculate_title_hash(title)
                    hashes.append(title_hash)
                    prepared_items.append(
                        {
                            "link": item.get("link", ""),
                            "keyword": keyword,
                            "title": title,
                            "description": item.get("description", ""),
                            "pubDate": pub_date,
                            "publisher": item.get("publisher", ""),
                            "pubDate_ts": parse_date_to_ts(pub_date),
                            "title_hash": title_hash,
                        }
                    )

                with conn:
                    placeholders = ",".join(["?"] * len(hashes))
                    cursor = conn.execute(
                        f"""
                        SELECT n.title_hash
                        FROM news n
                        JOIN news_keywords nk ON nk.link = n.link
                        WHERE nk.keyword = ? AND n.title_hash IN ({placeholders})
                        """,
                        [keyword] + hashes,
                    )
                    existing_hashes = {row[0] for row in cursor.fetchall()}
                    seen_hashes = set(existing_hashes)

                    news_insert_data: List[Tuple[Any, ...]] = []
                    kw_insert_data: List[Tuple[Any, ...]] = []

                    for item in prepared_items:
                        title_hash = item["title_hash"]
                        is_dup = title_hash in seen_hashes
                        if is_dup:
                            duplicate_count += 1
                        else:
                            added_count += 1
                        seen_hashes.add(title_hash)

                        news_insert_data.append(
                            (
                                item["link"],
                                item["keyword"],
                                item["title"],
                                item["description"],
                                item["pubDate"],
                                item["publisher"],
                                item["pubDate_ts"],
                                item["title_hash"],
                            )
                        )
                        kw_insert_data.append((item["link"], keyword, 1 if is_dup else 0))

                    conn.executemany(
                        """
                        INSERT INTO news
                        (link, keyword, title, description, pubDate, publisher, pubDate_ts, title_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(link) DO UPDATE SET
                            keyword = CASE WHEN keyword IS NULL OR keyword = '' THEN excluded.keyword ELSE keyword END,
                            title = excluded.title,
                            description = excluded.description,
                            pubDate = excluded.pubDate,
                            publisher = excluded.publisher,
                            pubDate_ts = CASE WHEN excluded.pubDate_ts > 0 THEN excluded.pubDate_ts ELSE pubDate_ts END,
                            title_hash = excluded.title_hash
                        """,
                        news_insert_data,
                    )

                    conn.executemany(
                        """
                        INSERT INTO news_keywords (link, keyword, is_duplicate)
                        VALUES (?, ?, ?)
                        ON CONFLICT(link, keyword) DO UPDATE SET
                            is_duplicate = excluded.is_duplicate
                        """,
                        kw_insert_data,
                    )

            return added_count, duplicate_count
        except sqlite3.Error as e:
            logger.error(f"DB Batch Upsert Error: {e}")
            return 0, 0
        finally:
            self.return_connection(conn)

    def fetch_news(
        self,
        keyword: str,
        filter_txt: str = "",
        sort_mode: str = "최신순",
        only_bookmark: bool = False,
        only_unread: bool = False,
        hide_duplicates: bool = False,
        exclude_words: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """뉴스 조회 - 안전한 버전 (날짜 필터 추가)"""
        conn = self.get_connection()
        news_items: List[Dict[str, Any]] = []
        scope_meta = (
            f"kw={keyword}|bookmark={int(only_bookmark)}|unread={int(only_unread)}|"
            f"hide_dup={int(hide_duplicates)}|ex={len(exclude_words) if exclude_words else 0}|"
            f"limit={limit}|offset={offset}"
        )
        try:
            with perf_timer("db.fetch_news", scope_meta):
                params: List[Any] = []

                if only_bookmark:
                    query = (
                        """
                        SELECT
                            n.link,
                            n.title,
                            n.description,
                            n.pubDate,
                            n.publisher,
                            n.is_read,
                            n.is_bookmarked,
                            n.pubDate_ts,
                            n.created_at,
                            n.notes,
                            n.title_hash,
                            CASE
                                WHEN EXISTS (
                                    SELECT 1 FROM news_keywords nk
                                    WHERE nk.link = n.link AND nk.is_duplicate = 1
                                ) THEN 1
                                ELSE 0
                            END AS is_duplicate
                        FROM news n
                        WHERE n.is_bookmarked = 1
                        """
                    )
                else:
                    query = (
                        """
                        SELECT
                            n.link,
                            n.title,
                            n.description,
                            n.pubDate,
                            n.publisher,
                            n.is_read,
                            n.is_bookmarked,
                            n.pubDate_ts,
                            n.created_at,
                            n.notes,
                            n.title_hash,
                            nk.is_duplicate AS is_duplicate
                        FROM news n
                        JOIN news_keywords nk ON nk.link = n.link
                        WHERE nk.keyword = ?
                        """
                    )
                    params.append(keyword)

                if only_unread:
                    query += " AND n.is_read = 0"

                if hide_duplicates:
                    if only_bookmark:
                        query += " AND NOT EXISTS (SELECT 1 FROM news_keywords nk WHERE nk.link = n.link AND nk.is_duplicate = 1)"
                    else:
                        query += " AND nk.is_duplicate = 0"

                if filter_txt:
                    query += " AND (n.title LIKE ? OR n.description LIKE ?)"
                    wildcard = f"%{filter_txt}%"
                    params.extend([wildcard, wildcard])

                if exclude_words:
                    for exclude_word in exclude_words:
                        if not exclude_word:
                            continue
                        query += " AND NOT (n.title LIKE ? OR n.description LIKE ?)"
                        wildcard = f"%{exclude_word}%"
                        params.extend([wildcard, wildcard])

                if start_date:
                    try:
                        s_ts = datetime.strptime(start_date, "%Y-%m-%d").timestamp()
                        query += " AND n.pubDate_ts >= ?"
                        params.append(s_ts)
                    except ValueError:
                        logger.warning(f"Invalid start_date format: {start_date}")

                if end_date:
                    try:
                        e_ts = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp()
                        query += " AND n.pubDate_ts < ?"
                        params.append(e_ts)
                    except ValueError:
                        logger.warning(f"Invalid end_date format: {end_date}")

                if sort_mode == "최신순":
                    query += " ORDER BY n.pubDate_ts DESC"
                else:
                    query += " ORDER BY n.pubDate_ts ASC"

                safe_offset = max(0, int(offset))
                if limit is not None:
                    query += " LIMIT ? OFFSET ?"
                    params.append(max(0, int(limit)))
                    params.append(safe_offset)

                cursor = conn.cursor()
                cursor.execute(query, params)
                columns = [column[0] for column in cursor.description]
                for row in cursor.fetchall():
                    news_items.append(dict(zip(columns, row)))
        except Exception as e:
            logger.error(f"뉴스 조회 오류: {e}")
        finally:
            self.return_connection(conn)

        return news_items

    def count_news(
        self,
        keyword: str,
        only_bookmark: bool = False,
        only_unread: bool = False,
        hide_duplicates: bool = False,
        filter_txt: str = "",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> int:
        """뉴스 개수 조회 (필터 적용)."""
        conn = self.get_connection()
        scope_meta = (
            f"kw={keyword}|bookmark={int(only_bookmark)}|unread={int(only_unread)}|"
            f"hide_dup={int(hide_duplicates)}"
        )
        try:
            with perf_timer("db.count_news", scope_meta):
                params: List[Any] = []
                if only_bookmark:
                    query = "SELECT COUNT(*) FROM news n WHERE n.is_bookmarked = 1"
                else:
                    query = (
                        "SELECT COUNT(*) FROM news n "
                        "JOIN news_keywords nk ON nk.link = n.link "
                        "WHERE nk.keyword = ?"
                    )
                    params.append(keyword)

                if only_unread:
                    query += " AND n.is_read = 0"

                if hide_duplicates:
                    if only_bookmark:
                        query += " AND NOT EXISTS (SELECT 1 FROM news_keywords nk WHERE nk.link = n.link AND nk.is_duplicate = 1)"
                    else:
                        query += " AND nk.is_duplicate = 0"

                if filter_txt:
                    query += " AND (n.title LIKE ? OR n.description LIKE ?)"
                    wildcard = f"%{filter_txt}%"
                    params.extend([wildcard, wildcard])

                if start_date:
                    try:
                        s_ts = datetime.strptime(start_date, "%Y-%m-%d").timestamp()
                        query += " AND n.pubDate_ts >= ?"
                        params.append(s_ts)
                    except ValueError:
                        logger.warning(f"Invalid start_date format: {start_date}")

                if end_date:
                    try:
                        e_ts = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp()
                        query += " AND n.pubDate_ts < ?"
                        params.append(e_ts)
                    except ValueError:
                        logger.warning(f"Invalid end_date format: {end_date}")

                cursor = conn.execute(query, params)
                row = cursor.fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error(f"count_news 오류: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def get_counts(self, keyword: str) -> int:
        """특정 키워드 뉴스 개수"""
        conn = self.get_connection()
        try:
            with perf_timer("db.get_counts", f"kw={keyword}"):
                cursor = conn.execute("SELECT COUNT(*) FROM news_keywords WHERE keyword=?", (keyword,))
                return cursor.fetchone()[0] or 0
        except Exception as e:
            logger.error(f"get_counts 오류: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def get_unread_count(self, keyword: str) -> int:
        """안 읽은 뉴스 개수"""
        conn = self.get_connection()
        try:
            with perf_timer("db.get_unread_count", f"kw={keyword}"):
                cursor = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM news n
                    JOIN news_keywords nk ON nk.link = n.link
                    WHERE nk.keyword = ? AND n.is_read = 0
                    """,
                    (keyword,),
                )
                return cursor.fetchone()[0] or 0
        except Exception as e:
            logger.error(f"get_unread_count 오류: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def get_unread_counts_by_keywords(self, keywords: List[str]) -> Dict[str, int]:
        """여러 키워드의 미읽음 기사 개수를 한 번에 조회."""
        if not keywords:
            return {}

        cleaned = [k for k in keywords if isinstance(k, str) and k.strip()]
        if not cleaned:
            return {}

        conn = self.get_connection()
        try:
            with perf_timer("db.get_unread_counts_by_keywords", f"kw_count={len(cleaned)}"):
                placeholders = ",".join(["?"] * len(cleaned))
                query = f"""
                    SELECT nk.keyword, COUNT(*) AS unread_count
                    FROM news_keywords nk
                    JOIN news n ON n.link = nk.link
                    WHERE nk.keyword IN ({placeholders}) AND n.is_read = 0
                    GROUP BY nk.keyword
                """
                rows = conn.execute(query, cleaned).fetchall()
                unread_by_kw: Dict[str, int] = {k: 0 for k in cleaned}
                for row in rows:
                    unread_by_kw[str(row[0])] = int(row[1])
                return unread_by_kw
        except Exception as e:
            logger.error(f"get_unread_counts_by_keywords 오류: {e}")
            return {k: 0 for k in cleaned}
        finally:
            self.return_connection(conn)

    ALLOWED_UPDATE_FIELDS = {'is_read', 'is_bookmarked', 'notes', 'is_duplicate'}
    
    def update_status(self, link: str, field: str, value) -> bool:
        """뉴스 상태 업데이트 - SQL Injection 방지 버전"""
        # 필드 화이트리스트 검증
        if field not in self.ALLOWED_UPDATE_FIELDS:
            logger.error(f"허용되지 않은 필드: {field}")
            return False
        
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(f"UPDATE news SET {field} = ? WHERE link = ?", (value, link))
            return True
        except sqlite3.Error as e:
            logger.error(f"DB Update Error: {e}")
            return False
        finally:
            self.return_connection(conn)
    
    def save_note(self, link: str, note: str) -> bool:
        """메모 저장"""
        return self.update_status(link, "notes", note)
    
    def get_note(self, link: str) -> str:
        """메모 조회"""
        conn = self.get_connection()
        try:
            cursor = conn.execute("SELECT notes FROM news WHERE link=?", (link,))
            result = cursor.fetchone()
            return result[0] if result and result[0] else ""
        except Exception as e:
            logger.error(f"get_note 오류: {e}")
            return ""
        finally:
            self.return_connection(conn)
    
    def delete_old_news(self, days: int) -> int:
        """오래된 뉴스 삭제"""
        conn = self.get_connection()
        cutoff = (datetime.now() - timedelta(days=days)).timestamp()
        try:
            with conn:
                cur = conn.execute(
                    "DELETE FROM news WHERE is_bookmarked=0 AND pubDate_ts < ?", 
                    (cutoff,)
                )
                return cur.rowcount
        except Exception as e:
            logger.error(f"delete_old_news 오류: {e}")
            return 0
        finally:
            self.return_connection(conn)
    
    def delete_all_news(self) -> int:
        """모든 뉴스 삭제 (북마크 제외)"""
        conn = self.get_connection()
        try:
            with conn:
                cur = conn.execute("DELETE FROM news WHERE is_bookmarked=0")
                return cur.rowcount
        except Exception as e:
            logger.error(f"delete_all_news 오류: {e}")
            return 0
        finally:
            self.return_connection(conn)
    
    def get_statistics(self) -> Dict[str, int]:
        """통계 정보"""
        conn = self.get_connection()
        try:
            stats = {}
            stats['total'] = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
            stats['unread'] = conn.execute("SELECT COUNT(*) FROM news WHERE is_read=0").fetchone()[0]
            stats['bookmarked'] = conn.execute("SELECT COUNT(*) FROM news WHERE is_bookmarked=1").fetchone()[0]
            stats['with_notes'] = conn.execute("SELECT COUNT(*) FROM news WHERE notes IS NOT NULL AND notes != ''").fetchone()[0]
            stats['duplicates'] = conn.execute("SELECT COUNT(*) FROM news WHERE is_duplicate=1").fetchone()[0]
            return stats
        except Exception as e:
            logger.error(f"get_statistics 오류: {e}")
            return {'total': 0, 'unread': 0, 'bookmarked': 0, 'with_notes': 0, 'duplicates': 0}
        finally:
            self.return_connection(conn)
    
    def get_top_publishers(self, keyword: Optional[str] = None, limit: int = 10) -> List[Tuple[str, int]]:
        """주요 언론사 통계"""
        conn = self.get_connection()
        try:
            if keyword:
                cursor = conn.execute("""
                    SELECT n.publisher, COUNT(*) as count 
                    FROM news n
                    JOIN news_keywords nk ON nk.link = n.link
                    WHERE nk.keyword=? 
                    GROUP BY n.publisher 
                    ORDER BY count DESC 
                    LIMIT ?
                """, (keyword, limit))
            else:
                cursor = conn.execute("""
                    SELECT publisher, COUNT(*) as count 
                    FROM news 
                    GROUP BY publisher 
                    ORDER BY count DESC 
                    LIMIT ?
                """, (limit,))
            return [(row[0], row[1]) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"get_top_publishers 오류: {e}")
            return []
        finally:
            self.return_connection(conn)
    
    def mark_all_as_read(self, keyword: str, only_bookmark: bool) -> int:
        """모든 기사 읽음 처리"""
        conn = self.get_connection()
        count = 0
        try:
            with conn:
                if only_bookmark:
                    cursor = conn.execute("UPDATE news SET is_read=1 WHERE is_bookmarked=1 AND is_read=0")
                else:
                    cursor = conn.execute(
                        """
                        UPDATE news
                        SET is_read=1
                        WHERE is_read=0
                          AND link IN (SELECT link FROM news_keywords WHERE keyword=?)
                        """,
                        (keyword,),
                    )
                count = cursor.rowcount
        except Exception as e:
            logger.error(f"일괄 읽음 처리 오류: {e}")
            raise
        finally:
            self.return_connection(conn)
        return count

    def close(self):
        """모든 연결 종료 - 안전한 버전"""
        self._closed = True
        closed_count = 0
        
        # 비상 연결 정리 (경고 로그만 남김 - 이미 반환해야 했지만 남아있는 연결)
        with self._lock:
            emergency_count = len(self._emergency_connections)
            if emergency_count > 0:
                logger.warning(f"비상 연결 {emergency_count}개가 정리되지 않고 남아있음")
            self._emergency_connections.clear()
        
        try:
            while not self.connection_pool.empty():
                try:
                    conn = self.connection_pool.get_nowait()
                    conn.close()
                    closed_count += 1
                except (sqlite3.Error, Exception):
                    break
            logger.info(f"DB 연결 {closed_count}개 정상 종료")
        except Exception as e:
            logger.error(f"DB 종료 중 오류: {e}")
