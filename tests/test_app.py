import random
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import MAX_BYTES, create_app
from search_engine import Store, highlights, normalize, terms_for


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / 'test.sqlite3')) as browser:
        yield browser


def upload(client, name, body):
    data = body.encode('utf-8') if isinstance(body, str) else body
    return client.post('/api/documents', files=[('files', (name, data))]).json()['results'][0]


@pytest.mark.parametrize('query', ['文件', '文', '文件搜尋', 'PYTHON', 'python 文件', 'SQLite 搜尋', '搜尋引擎', 'py 文'])
def test_bilingual_search(client, query):
    document = upload(client, '研究.md', '這是個人文件搜尋引擎，使用 Python 與 SQLite。')
    upload(client, '另一份.txt', '這裡只有其他內容。')
    response = client.get('/api/search', params={'q': query})
    assert response.status_code == 200
    data = response.json()
    assert data['total'] == 1
    assert data['items'][0]['id'] == document['id']
    assert data['items'][0]['snippet']['highlights']


@pytest.mark.parametrize('query', ['" OR "', "' OR 1=1 --", 'a*b', '%_', 'foo:bar', 'AND', 'C++', 'NEAR(x)', '"""', 'a-b'])
def test_special_characters_are_literals(client, query):
    upload(client, 'literal.md', f'The exact string is {query} in this document.')
    upload(client, 'unrelated.md', 'nothing to match')
    actual = client.get('/api/search', params={'q':query})
    assert actual.status_code == 200
    assert actual.json()['total'] == 1
    assert client.get('/api/documents').json()['total'] == 2


def test_title_body_and_semantics(client):
    upload(client, 'Python 工作.md', '文件搜尋功能')
    upload(client, 'Python.md', '完全不同')
    assert client.get('/api/search', params={'q':'工作 搜尋 Python'}).json()['total'] == 1
    assert client.get('/api/search', params={'q':'不存在'}).json()['total'] == 0
    assert client.get('/api/search', params={'q':'  \t '}).json()['total'] == 2


def test_upload_validation_and_deduplication(client):
    files = [
        ('files', ('note.md', '筆記內容'.encode('utf-8-sig'))),
        ('files', ('copy.txt', '筆記內容'.encode('utf-8'))),
        ('files', ('note.md', '另一段內容'.encode('utf-8'))),
        ('files', ('bad.pdf', b'PDF')),
        ('files', ('bad.txt', b'\xff\xfe')),
        ('files', ('empty.txt', b' \r\n')),
        ('files', ('binary.txt', b'a\x00b')),
        ('files', ('too-large.md', b'x' * (MAX_BYTES + 1))),
    ]
    results = client.post('/api/documents', files=files).json()['results']
    assert [row['status'] for row in results] == ['imported','duplicate','imported','error','error','error','error','error']
    assert results[0]['id'] == results[1]['id']
    assert results[2]['id'] != results[0]['id']
    assert 'UTF-8' in results[4]['message']
    assert '5 MB' in results[-1]['message']


def test_exact_size_limit(client):
    result = upload(client, 'exact.txt', b'x' * MAX_BYTES)
    assert result['status'] == 'imported'


def test_delete_and_restart(tmp_path):
    path = tmp_path / 'persistent.sqlite3'
    with TestClient(create_app(path)) as client:
        doc = upload(client, 'stored.md', '永久保存 SQLite 文件')
    with TestClient(create_app(path)) as client:
        assert client.get('/api/search', params={'q':'SQLite'}).json()['total'] == 1
        assert client.delete(f'/api/documents/{doc["id"]}').status_code == 200
        assert client.get('/api/search', params={'q':'SQLite'}).json()['total'] == 0
        assert client.get('/api/search', params={'q':'文件'}).json()['total'] == 0
        assert client.get(f'/api/documents/{doc["id"]}').status_code == 404
        assert client.delete(f'/api/documents/{doc["id"]}').status_code == 404
    with TestClient(create_app(path)) as client:
        assert client.get('/api/documents').json()['total'] == 0


def test_pagination_and_ties(client):
    for index in range(23):
        upload(client, f'note-{index}.txt', f'common content {index}')
    with client.app.state.store.connect() as connection:
        connection.execute("UPDATE documents SET imported_at='2026-01-01T00:00:00+00:00'")
    first = client.get('/api/search', params={'q':'co', 'page':1}).json()
    second = client.get('/api/search', params={'q':'co', 'page':2}).json()
    assert first['total'] == 23 and first['pages'] == 2
    assert len(first['items']) == 20 and len(second['items']) == 3
    ids = [item['id'] for item in first['items'] + second['items']]
    assert ids == list(range(23, 0, -1))
    assert client.get('/api/search', params={'page':0}).status_code == 422
    assert client.get('/api/search', params={'page':100}).json()['items'] == []


@pytest.mark.parametrize('query', ['python', 'py'])
def test_title_weight(client, query):
    title_hit = upload(client, 'python.md', 'a brief note about code')
    upload(client, 'reading.md', 'a brief note about python')
    assert client.get('/api/search', params={'q':query}).json()['items'][0]['id'] == title_hit['id']


def test_unicode_offsets_and_xss(client):
    body = '📝😀 文件搜尋 <script>window.hacked=true</script>'
    doc = upload(client, '<img src=x onerror=alert(1)>.md', body)
    item = client.get(f'/api/documents/{doc["id"]}', params={'q':'文件搜尋'}).json()
    assert item['body'] == body
    assert [body[a:b] for a,b in item['highlights']] == ['文件搜尋']
    response = client.get('/')
    assert "script-src 'self'" in response.headers['Content-Security-Policy']
    assert '<script>window.hacked=true</script>' not in response.text


def test_highlights_merge_and_snippet(client):
    assert highlights('aaaa', ['aaa', 'aa']) == [[0,4]]
    body = '前' * 300 + '關鍵字 Python' + '後' * 300
    upload(client, 'long.md', body)
    snippet = client.get('/api/search', params={'q':'關鍵字'}).json()['items'][0]['snippet']
    assert snippet['has_before'] and snippet['has_after']
    assert len(snippet['text']) == 240
    assert snippet['text'][slice(*snippet['highlights'][0])] == '關鍵字'


def test_local_origin_and_validation(client):
    assert client.post('/api/documents', files={'files':('a.txt',b'ok')}, headers={'Origin':'https://example.org'}).status_code == 403
    assert client.get('/api/search', params={'q':'x' * 501}).status_code == 422
    assert client.get('/api/search', params={'q':'\x00'}).status_code == 422
    assert client.get('/', headers={'Host':'evil.example'}).status_code == 400


def test_atomic_insert_delete(tmp_path):
    store = Store(tmp_path / 'atomic.sqlite3')
    store.initialize()
    with pytest.raises(RuntimeError):
        with store.connect() as conn:
            store.insert(conn, 'atomic.txt', 'rollback insertion')
            raise RuntimeError('simulate failure')
    assert store.matching_ids('rollback') == []
    document = store.add('atomic.txt', 'committed content')
    with pytest.raises(RuntimeError):
        with store.connect() as conn:
            conn.execute('DELETE FROM documents WHERE id=?', (document['id'],))
            raise RuntimeError('simulate failure')
    assert store.matching_ids('committed') == [document['id']]


def test_index_matches_independent_reference(tmp_path):
    rng = random.Random(42)
    store = Store(tmp_path / 'reference.sqlite3')
    store.initialize()
    pieces = ['文件搜尋', '筆記', 'Python', 'SQLite', 'abc"def', 'a*b', '100%', 'x_y', '😀', 'éclair', 'C++', '其他']
    corpus = []
    for index in range(100):
        title = f'{rng.choice(pieces)}-{index}.md'
        body = ' '.join(rng.choices(pieces, k=10)) + str(index)
        doc = store.add(title, body)
        corpus.append((doc['id'], normalize(title), normalize(body)))
    for query in pieces + ['文件 Python', '筆 SQLite', 'abc"def a*b', '😀 筆', '不存在']:
        terms = terms_for(query)
        expected = [i for i,t,b in corpus if all(term in t or term in b for term in terms)]
        assert store.matching_ids(query, True) == expected
        assert store.matching_ids(query, False) == expected
