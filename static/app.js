'use strict';
const $ = (selector) => document.querySelector(selector);
const state = { query: '', page: 1, pages: 0, current: null, sequence: 0, uploading: false, data: null, library: null, preview: null, uploadResults: null, uploadCount: 0, uploadFailed: false, error: null, loading: false, loadFailed: false };
const date = (value) => new Intl.DateTimeFormat(language === 'en' ? 'en-US' : 'zh-TW', {year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
const size = (bytes) => bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function highlighted(node, text, ranges = []) {
  // Server offsets are Unicode code points; Array.from also handles emoji correctly.
  const chars = Array.from(text);
  node.replaceChildren();
  let cursor = 0;
  for (const [start, end] of ranges) {
    node.append(document.createTextNode(chars.slice(cursor, start).join('')));
    node.append(element('mark', '', chars.slice(start, end).join('')));
    cursor = end;
  }
  node.append(document.createTextNode(chars.slice(cursor).join('')));
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = '請求失敗（{status}），請稍後再試。';
    try { const body = await response.json(); if (typeof body.detail === 'string') message = body.detail; } catch {}
    throw Object.assign(new Error(message), {values:{status:response.status}});
  }
  return response.json();
}

function showError(error) {
  state.error = error;
  $('#error').textContent = t(error instanceof TypeError ? '無法連線，請確認本機服務正在執行。' : error.message || '無法連線，請確認本機服務正在執行。', error.values);
  $('#error').hidden = false;
}

function emptyState(title, description, symbol = '▤') {
  const container = element('div', 'empty-state');
  container.append(element('div', 'empty-symbol', symbol), element('h3', '', t(title)), element('p', '', t(description)));
  return container;
}

function card(item) {
  const article = element('article', 'document-card');
  const ext = item.title.split('.').pop().toUpperCase();
  const main = element('div', 'document-main');
  const title = element('button', 'document-title');
  highlighted(title, item.title, item.title_highlights);
  title.addEventListener('click', () => openPreview(item.id));
  const snippet = element('p', 'document-snippet');
  highlighted(snippet, item.snippet.text, item.snippet.highlights);
  if (item.snippet.has_before) snippet.prepend(document.createTextNode('…'));
  if (item.snippet.has_after) snippet.append(document.createTextNode('…'));
  const meta = element('div', 'document-meta');
  meta.append(element('span', '', t('{date} 匯入', {date:date(item.imported_at)})), element('span', '', size(item.size_bytes)), element('span', '', `#${item.id}`));
  main.append(title, snippet, meta);
  const open = element('button', 'open-document', '↗');
  open.setAttribute('aria-label', t('預覽 {title}', {title:item.title}));
  open.addEventListener('click', () => openPreview(item.id));
  article.append(element('div', 'document-type', ext), main, open);
  return article;
}

async function refresh() {
  const sequence = ++state.sequence;
  state.error = null;
  state.loading = true;
  state.loadFailed = false;
  $('#error').hidden = true;
  $('#result-meta').textContent = t('正在尋找文字…');
  $('#results').setAttribute('aria-busy', 'true');
  $('#pagination').hidden = true;
  try {
    const params = new URLSearchParams({q: state.query, page: state.page});
    const [data, library] = await Promise.all([
      api(`/api/search?${params}`),
      state.query ? api('/api/documents') : Promise.resolve(null),
    ]);
    if (sequence !== state.sequence) return;
    if (state.page > 1 && state.page > data.pages) {
      state.page = Math.max(1, data.pages);
      return refresh();
    }
    state.pages = data.pages;
    state.data = data;
    state.library = library;
    renderResults();
  } catch (error) {
    if (sequence === state.sequence) {
      showError(error);
      state.loadFailed = true;
      renderLoadFailure();
    }
  } finally {
    if (sequence === state.sequence) { state.loading = false; $('#results').setAttribute('aria-busy', 'false'); }
  }
}

function renderResults() {
  const data = state.data;
  if (!data) return;
  $('#library-count').textContent = (state.library || data).total;
  $('#results-heading').replaceChildren(document.createTextNode(t(state.query ? '搜尋結果' : '所有文件') + ' '), element('span', '', data.total));
  $('#result-meta').textContent = state.query ? t('{total} 份文件 · {ms} ms', {total:data.total,ms:data.elapsed_ms}) : t('依匯入時間排序');
  $('#results').replaceChildren(...data.items.map(card));
  if (!data.items.length) $('#results').append(state.query
    ? emptyState('還沒找到這段文字', '試試更短的關鍵字，或減少同時搜尋的詞。', '⌕')
    : emptyState('你的知識庫，從第一份文件開始', '匯入筆記、文章或靈感清單，讓重要的文字不再散落。'));
  $('#pagination').hidden = data.pages <= 1;
  $('#page-info').textContent = `${state.page} / ${data.pages}`;
  $('#previous').disabled = state.page <= 1;
  $('#next').disabled = state.page >= data.pages;
}

function renderLoadFailure() {
  $('#result-meta').textContent = t('讀取失敗');
  $('#results').replaceChildren(emptyState('暫時無法讀取文件', '確認服務正在執行後，按搜尋重新載入。'));
}

function renderUpload() {
  const status = $('#upload-status');
  if (state.uploadFailed) {
    status.replaceChildren(element('p', 'failed', t('匯入未完成，請確認連線後再試。已成功的文件再次匯入時會自動略過。')));
  } else if (state.uploadResults) {
    const results = state.uploadResults;
    const imported = results.filter(item => item.status === 'imported').length;
    status.replaceChildren(element('h3', '', t('匯入完成 · 新增 {imported} 份 / 共 {total} 份', {imported,total:results.length})));
    for (const result of results) status.append(element('p', result.status === 'error' ? 'failed' : '', `${result.status === 'imported' ? '✓' : result.status === 'duplicate' ? '–' : '×'} ${result.filename} — ${t(result.message)}`));
  } else if (state.uploading) {
    status.replaceChildren(element('h3', '', t('正在匯入 {count} 份文件…', {count:state.uploadCount})));
  }
}

async function upload(files) {
  if (!files.length || state.uploading) return;
  state.uploading = true;
  state.uploadCount = files.length;
  state.uploadResults = null;
  state.uploadFailed = false;
  $('#import-button').disabled = $('#choose-files').disabled = true;
  const status = $('#upload-status');
  status.hidden = false;
  renderUpload();
  const payload = new FormData();
  const rejected = [];
  for (const file of files) {
    if (file.size > 5 * 1024 * 1024) rejected.push({filename:file.name,status:'error',message:'檔案超過 5 MB 上限。'});
    else payload.append('files', file);
  }
  try {
    const response = payload.has('files') ? await api('/api/documents', {method:'POST',body:payload}) : {results:[]};
    state.uploadResults = [...response.results, ...rejected];
    renderUpload();
    state.page = 1;
    await refresh();
  } catch (error) {
    state.uploadFailed = true;
    renderUpload();
    showError(error);
  } finally {
    state.uploading = false;
    $('#import-button').disabled = $('#choose-files').disabled = false;
    $('#file-input').value = '';
  }
}

let previewSequence = 0;
async function openPreview(id) {
  const sequence = ++previewSequence;
  try {
    const document = await api(`/api/documents/${id}?${new URLSearchParams({q:state.query})}`);
    if (sequence !== previewSequence) return;
    state.current = id;
    state.preview = document;
    highlighted($('#preview-title'), document.title, document.title_highlights);
    renderPreviewMeta();
    highlighted($('#preview-body'), document.body, document.highlights);
    $('#preview').showModal();
    $('#preview-body').scrollTop = 0;
  } catch (error) { showError(error); }
}

function renderPreviewMeta() {
  const item = state.preview;
  if (item) $('#preview-meta').textContent = `${t('{date} 匯入', {date:date(item.imported_at)})} · ${size(item.size_bytes)} · #${item.id}`;
}

document.addEventListener('languagechange', () => {
  if (state.loadFailed) renderLoadFailure();
  else renderResults();
  if (state.loading) {
    $('#result-meta').textContent = t('正在尋找文字…');
    $('#pagination').hidden = true;
  }
  renderUpload();
  renderPreviewMeta();
  if (state.error) showError(state.error);
});

$('#search-form').addEventListener('submit', event => {
  event.preventDefault(); state.query = $('#query').value.trim(); state.page = 1; refresh();
});
$('#query').addEventListener('search', () => { if (!$('#query').value) { state.query=''; state.page=1; refresh(); } });
$('#library-button').addEventListener('click', () => { state.query=''; state.page=1; $('#query').value=''; refresh(); });
$('#previous').addEventListener('click', () => { if(state.page>1){state.page--;refresh();} });
$('#next').addEventListener('click', () => { if(state.page<state.pages){state.page++;refresh();} });
for (const selector of ['#import-button','#choose-files']) $(selector).addEventListener('click', () => $('#file-input').click());
$('#file-input').addEventListener('change', event => upload(Array.from(event.target.files)));
const dropzone = $('#dropzone');
let dragDepth = 0;
dropzone.addEventListener('dragenter', event => { event.preventDefault(); dragDepth++; dropzone.classList.add('dragging'); });
dropzone.addEventListener('dragover', event => event.preventDefault());
dropzone.addEventListener('dragleave', () => { if (--dragDepth <= 0) dropzone.classList.remove('dragging'); });
dropzone.addEventListener('drop', event => { event.preventDefault(); dragDepth=0; dropzone.classList.remove('dragging'); upload(Array.from(event.dataTransfer.files)); });
window.addEventListener('dragover', event => event.preventDefault());
window.addEventListener('drop', event => event.preventDefault());
$('#close-preview').addEventListener('click', () => $('#preview').close());
$('#delete-document').addEventListener('click', () => $('#delete-confirm').showModal());
$('#cancel-delete').addEventListener('click', () => $('#delete-confirm').close());
$('#confirm-delete').addEventListener('click', async () => {
  $('#confirm-delete').disabled = true;
  try {
    await api(`/api/documents/${state.current}`, {method:'DELETE'});
    $('#delete-confirm').close(); $('#preview').close(); state.current=null;
    await refresh();
  } catch (error) {
    $('#delete-confirm').close(); $('#preview').close(); showError(error);
  } finally { $('#confirm-delete').disabled = false; }
});
document.addEventListener('keydown', event => {
  if (event.key === '/' && !['INPUT','TEXTAREA'].includes(document.activeElement.tagName) && !$('#preview').open && !$('#delete-confirm').open) {
    event.preventDefault(); $('#query').focus();
  }
});
refresh();
