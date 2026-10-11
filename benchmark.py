"""Reproducible matching benchmarks; synthetic data only, separate from user DB."""
import argparse
import hashlib
import json
import math
import platform
import random
import sqlite3
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from search_engine import Store

ROOT = Path(__file__).resolve().parent
SEED = 20261010
TOPICS = [
    ('搜尋系統', '倒排索引 文件搜尋 查詢最佳化 SQLite retrieval indexing'),
    ('機器學習', '特徵工程 模型訓練 Python machine learning inference'),
    ('網路協定', '封包分析 網路協定 TCP connection latency server'),
    ('資料結構', '二元樹 雜湊表 演算法 graph tree algorithm'),
    ('設計筆記', '互動設計 使用者研究 無障礙 typography design interface'),
    ('日常閱讀', '旅行觀察 閱讀心得 生活紀錄 books walking journal'),
    ('資料安全', '存取控制 加密備份 權限設計 security encryption audit'),
    ('專案管理', '需求分析 任務規劃 團隊合作 project planning review'),
]
QUERIES = {
    'long': ['文件搜尋', 'Python', '網路協定', 'machine learning', '倒排索引 SQLite', '不存在的查詢'],
    'mixed': ['SQLite 文', 'Python 學', 'TCP 網', 'project 任'],
    'short': ['文', '筆記', 'py', '網 路'],
}


def corpus(count):
    rng = random.Random(SEED)
    for index in range(count):
        topic, vocabulary = TOPICS[rng.randrange(len(TOPICS))]
        words = vocabulary.split()
        paragraphs = [' '.join(rng.choices(words, k=22)) for _ in range(5)]
        body = f'# {topic} / {index:05d}\n\n' + '\n\n'.join(paragraphs)
        if index % 37 == 0:
            body += '\n\n特殊記錄 C++ foo:bar 100% a_b 📝'
        yield f'{topic}-{index:05d}.md', body


def percentile95(values):
    return sorted(values)[math.ceil(.95 * len(values)) - 1]


def run(count, repeats, folder):
    # Each run gets a new filename; never overwrite a user's database.
    path = folder / f'corpus-{count}-{time.time_ns()}.sqlite3'
    store = Store(path)
    store.initialize()
    digest = hashlib.sha256()
    raw_size = 0
    started = time.perf_counter()
    with store.connect() as conn:
        for title, body in corpus(count):
            encoded = (title + '\0' + body).encode('utf-8')
            digest.update(encoded)
            raw_size += len(body.encode('utf-8'))
            store.insert(conn, title, body)
        conn.execute("INSERT INTO document_fts(document_fts) VALUES('optimize')")
    build_seconds = time.perf_counter() - started
    with store.connect() as conn:
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    record = {'documents':count, 'build_seconds':round(build_seconds,3),
              'database_bytes':path.stat().st_size, 'source_bytes':raw_size,
              'corpus_sha256':digest.hexdigest(), 'groups':{}}
    with store.connect() as conn:
        for group, queries in QUERIES.items():
            timings = {'index':[], 'scan':[]}
            hits = {}
            for query in queries:
                indexed = store.matching_ids(query, True, conn)
                scanned = store.matching_ids(query, False, conn)
                assert indexed == scanned, f'Mismatch: {query}'
                hits[query] = len(indexed)
            # Interleave methods to reduce order bias; one warmed shared connection.
            for repeat in range(repeats):
                for query in queries:
                    methods = [('index',True),('scan',False)]
                    if repeat % 2:
                        methods.reverse()
                    for label, indexed in methods:
                        before = time.perf_counter()
                        store.matching_ids(query, indexed, conn)
                        timings[label].append((time.perf_counter() - before) * 1000)
            record['groups'][group] = {
                'hits':hits, 'equal_results':True,
                **{method:{'median_ms':round(statistics.median(values),3),
                           'p95_ms':round(percentile95(values),3), 'samples':len(values)}
                   for method,values in timings.items()},
            }
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sizes', type=int, nargs='+', default=[1000,10000])
    parser.add_argument('--repeats', type=int, default=10)
    parser.add_argument('--output', type=Path, default=ROOT / 'benchmark-results.json')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'benchmark-data')
    args = parser.parse_args()
    if args.repeats < 1 or any(count < 1 for count in args.sizes):
        parser.error('sizes and repeats must be positive')
    args.data_dir.mkdir(parents=True, exist_ok=True)
    report = {'seed':SEED, 'created_utc':datetime.now(timezone.utc).isoformat(),
              'python':platform.python_version(), 'sqlite':sqlite3.sqlite_version,
              'platform':platform.platform(), 'processor':platform.processor(),
              'method':'Warm matching IDs, same connection, exact predicates, ID ordering; excludes BM25, snippets, HTTP and UI. Short queries use scan in both paths.',
              'repeats':args.repeats, 'results':[]}
    for count in args.sizes:
        print(f'Benchmarking {count} documents...', flush=True)
        report['results'].append(run(count,args.repeats,args.data_dir))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Report: {args.output}', flush=True)


if __name__ == '__main__':
    main()
