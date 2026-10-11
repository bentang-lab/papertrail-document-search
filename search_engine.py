"""Literal bilingual substring search with FTS5 candidate selection."""
from __future__ import annotations

import hashlib
import heapq
import math
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

PAGE_SIZE = 20
ASCII_LOWER = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')


def normalize(text: str) -> str:
    # English case-insensitivity without changing Unicode character offsets.
    return text.translate(ASCII_LOWER)


def terms_for(query: str) -> list[str]:
    return list(dict.fromkeys(normalize(query).split()))


def highlights(text: str, terms: list[str]) -> list[list[int]]:
    """Merged [start, end) ranges in Unicode code points, not UTF-16 units."""
    normalized = normalize(text)
    pending = []
    for term in terms:
        start = normalized.find(term)
        if start >= 0:
            heapq.heappush(pending, (start, term))
    merged = []
    # Merge as we go instead of allocating one interval for every occurrence.
    while pending:
        start, term = heapq.heappop(pending)
        end = start + len(term)
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
        next_start = normalized.find(term, start + 1)
        if next_start >= 0:
            heapq.heappush(pending, (next_start, term))
    return merged


def excerpt(body: str, terms: list[str]) -> dict:
    lowered = normalize(body)
    hits = [lowered.find(term) for term in terms if term in lowered]
    start = max(0, min(hits) - 60) if hits else 0
    end = min(len(body), start + 240)
    text = body[start:end]
    return {'text': text, 'highlights': highlights(text, terms),
            'start': start, 'has_before': start > 0, 'has_after': end < len(body)}


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    title_norm TEXT NOT NULL,
                    body_norm TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    imported_at TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(
                    title_norm, body_norm,
                    content='documents', content_rowid='id',
                    tokenize='trigram case_sensitive 1'
                );
                CREATE TRIGGER IF NOT EXISTS documents_insert AFTER INSERT ON documents BEGIN
                    INSERT INTO document_fts(rowid, title_norm, body_norm)
                    VALUES (new.id, new.title_norm, new.body_norm);
                END;
                CREATE TRIGGER IF NOT EXISTS documents_delete AFTER DELETE ON documents BEGIN
                    INSERT INTO document_fts(document_fts, rowid, title_norm, body_norm)
                    VALUES ('delete', old.id, old.title_norm, old.body_norm);
                END;
            ''')

    @staticmethod
    def insert(conn, title: str, body: str):
        digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
        cursor = conn.execute('''
            INSERT INTO documents(title, body, title_norm, body_norm,
                                  content_hash, imported_at, size_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(content_hash) DO NOTHING
        ''', (title, body, normalize(title), normalize(body), digest,
              datetime.now(timezone.utc).isoformat(), len(body.encode('utf-8'))))
        if cursor.rowcount:
            return {'status': 'imported', 'id': cursor.lastrowid}
        existing = conn.execute('SELECT id FROM documents WHERE content_hash=?', (digest,)).fetchone()
        return {'status': 'duplicate', 'id': existing['id']}

    def add(self, title: str, body: str):
        with self.connect() as conn:
            return self.insert(conn, title, body)

    @staticmethod
    def selection(terms: list[str], indexed=True):
        long_terms = [term for term in terms if len(term) >= 3]
        clauses, params = [], []
        source = 'documents d'
        if indexed and long_terms:
            source += ' JOIN document_fts ON document_fts.rowid=d.id'
            clauses.append('document_fts MATCH ?')
            # Quote every literal; never interpret user-supplied FTS operators.
            params.append(' AND '.join('"' + term.replace('"', '""') + '"' for term in long_terms))
        # Verify literal semantics identically for index and scan implementations.
        for term in terms:
            clauses.append('(instr(d.title_norm, ?) > 0 OR instr(d.body_norm, ?) > 0)')
            params.extend([term, term])
        return source, ' AND '.join(clauses) or '1', params, bool(indexed and long_terms)

    def matching_ids(self, query: str, indexed=True, conn=None):
        source, where, params, _ = self.selection(terms_for(query), indexed)
        sql = f'SELECT d.id FROM {source} WHERE {where} ORDER BY d.id'
        if conn is not None:
            return [row[0] for row in conn.execute(sql, params)]
        with self.connect() as database:
            return [row[0] for row in database.execute(sql, params)]

    def search(self, query='', page=1):
        started = time.perf_counter()
        terms = terms_for(query)
        source, where, params, ranked = self.selection(terms)
        if ranked:
            ordering, order_params = 'bm25(document_fts, 6.0, 1.0) ASC', []
        elif terms:
            ordering = '(' + ' + '.join('(instr(d.title_norm, ?) > 0)' for _ in terms) + ') DESC'
            order_params = terms
        else:
            ordering, order_params = 'd.imported_at DESC', []
        with self.connect() as conn:
            total = conn.execute(f'SELECT count(*) FROM {source} WHERE {where}', params).fetchone()[0]
            rows = conn.execute(f'''
                SELECT d.id, d.title, d.body, d.imported_at, d.size_bytes
                FROM {source} WHERE {where}
                ORDER BY {ordering}, d.imported_at DESC, d.id DESC LIMIT ? OFFSET ?
            ''', [*params, *order_params, PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item['snippet'] = excerpt(item.pop('body'), terms)
            item['title_highlights'] = highlights(item['title'], terms)
            items.append(item)
        return {'items': items, 'total': total, 'page': page, 'page_size': PAGE_SIZE,
                'pages': math.ceil(total / PAGE_SIZE),
                'elapsed_ms': round((time.perf_counter() - started) * 1000, 2),
                'strategy': 'trigram' if ranked else 'scan' if terms else 'browse'}

    def get(self, document_id: int, query=''):
        with self.connect() as conn:
            row = conn.execute('SELECT id, title, body, imported_at, size_bytes FROM documents WHERE id=?',
                               (document_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        terms = terms_for(query)
        item['highlights'] = highlights(item['body'], terms)
        item['title_highlights'] = highlights(item['title'], terms)
        return item

    def delete(self, document_id: int):
        with self.connect() as conn:
            return conn.execute('DELETE FROM documents WHERE id=?', (document_id,)).rowcount > 0
