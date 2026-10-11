from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from search_engine import Store

ROOT = Path(__file__).resolve().parent
MAX_BYTES = 5 * 1024 * 1024


def create_app(db_path=None):
    store = Store(db_path or os.environ.get('DOCUMENT_SEARCH_DB', ROOT / 'data' / 'documents.sqlite3'))

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        yield

    app = FastAPI(title='紙間 · 個人文件搜尋', lifespan=lifespan,
                  docs_url=None, redoc_url=None)
    app.state.store = store
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.middleware('http')
    async def local_origin(request, call_next):
        origin = request.headers.get('origin')
        expected = f'{request.url.scheme}://{request.headers.get("host", "")}'
        if request.method in {'POST', 'DELETE', 'PUT', 'PATCH'} and origin and origin != expected:
            return JSONResponse({'detail': '不接受跨來源的修改請求。'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.post('/api/documents')
    async def upload(files: list[UploadFile] = File(...)):
        results = []
        for file in files:
            title = (file.filename or '').replace('\\', '/').rsplit('/', 1)[-1]
            result = {'filename': title, 'status': 'error'}
            try:
                if Path(title).suffix.lower() not in {'.txt', '.md'}:
                    raise ValueError('僅支援 .txt 與 .md 檔案。')
                payload = bytearray()
                while chunk := await file.read(64 * 1024):
                    payload.extend(chunk)
                    if len(payload) > MAX_BYTES:
                        raise ValueError('檔案超過 5 MB 上限。')
                try:
                    body = payload.decode('utf-8-sig')
                except UnicodeDecodeError:
                    raise ValueError('無法以 UTF-8 讀取；請先另存為 UTF-8 編碼。')
                if '\x00' in body:
                    raise ValueError('檔案含有二進位或不支援的文字內容。')
                if not body.strip():
                    raise ValueError('檔案沒有可搜尋的文字。')
                result.update(await run_in_threadpool(store.add, title, body))
                result['message'] = '已加入文件庫' if result['status'] == 'imported' else '內容相同，已略過'
            except ValueError as exc:
                result['message'] = str(exc)
            finally:
                await file.close()
            results.append(result)
        return {'results': results}

    @app.get('/api/documents')
    def documents(page: int = Query(1, ge=1)):
        return store.search(page=page)

    @app.get('/api/search')
    def search(q: str = Query('', max_length=500), page: int = Query(1, ge=1)):
        if '\x00' in q:
            raise HTTPException(422, '查詢不能含有 NUL 字元。')
        return store.search(q, page)

    @app.get('/api/documents/{document_id}')
    def document(document_id: int, q: str = Query('', max_length=500)):
        item = store.get(document_id, q)
        if item is None:
            raise HTTPException(404, '找不到這份文件。')
        return item

    @app.delete('/api/documents/{document_id}')
    def delete(document_id: int):
        if not store.delete(document_id):
            raise HTTPException(404, '找不到這份文件。')
        return {'deleted': document_id}

    app.mount('/', StaticFiles(directory=ROOT / 'static', html=True), name='web')
    return app


app = create_app()
