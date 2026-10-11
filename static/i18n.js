'use strict';
// Keys are the original Traditional Chinese UI strings. Document text is never translated.
const EN = {
  '紙間 · 個人文件搜尋':'Papertrail · Personal Document Search',
  '紙間首頁':'Papertrail home', '紙':'P', '紙間':'Papertrail',
  '你的工作空間':'YOUR WORKSPACE', '文件庫':'Library',
  '只在這台電腦上':'Stored on this computer', '你的文字，你的空間。':'Your words. Your space.',
  '文件保留在本機，隨時找回想法。':'Keep your documents local and your ideas within reach.',
  '個人文件搜尋引擎 / v1.0':'Personal document search / v1.0',
  '工作空間':'Workspace', '本機模式':'Local mode',
  '讓想法，有跡可循。':'Find your train of thought.',
  '把散落的筆記放在一起，找到你記得的那一句。':'Bring your notes together. Find the words you remember.',
  '匯入文件':'Import files', '搜尋文件':'Search documents', '搜尋':'Search',
  '搜尋檔名、內容，或一個靈感…':'Search filenames, content, or an idea…',
  '支援中文、英文與多個關鍵字':'Search in English, Chinese, or both',
  '以空白分隔，同時符合所有詞':'Separate terms with spaces. All terms must match.',
  '匯入文件區':'File import area',
  '把文件拖進來，開始整理你的知識':'Drop your files here. Make room for ideas.',
  '或':'or', '選擇檔案':'choose files',
  '，支援 .txt、.md，每份最多 5 MB':' · .txt and .md · up to 5 MB each',
  '選擇要匯入的檔案':'Choose files to import', '文件列表':'Document list',
  '所有文件':'All documents', '搜尋結果':'Search results',
  '準備讀取文件庫':'Loading your library', '搜尋結果分頁':'Search result pages',
  '← 上一頁':'← Previous', '下一頁 →':'Next →',
  '每一份筆記，都是下一個想法的起點。':'Every note is the beginning of another idea.',
  '關閉全文預覽':'Close document preview', '純文字預覽 · 保留原始內容':'Plain text preview · Original content',
  '刪除文件':'Delete document', '移除這份文件？':'Remove this document?',
  '將從文件庫與搜尋索引中刪除，不會影響原始檔案。':'This removes the document from your library and search index. The original file stays untouched.',
  '保留文件':'Keep document', '確認刪除':'Confirm delete',
  '正在尋找文字…':'Searching your documents…', '依匯入時間排序':'Sorted by import date',
  '還沒找到這段文字':'No matching documents',
  '試試更短的關鍵字，或減少同時搜尋的詞。':'Try a shorter keyword or search for fewer terms.',
  '你的知識庫，從第一份文件開始':'Your library starts with one document',
  '匯入筆記、文章或靈感清單，讓重要的文字不再散落。':'Import notes, articles, or ideas to keep your words together.',
  '讀取失敗':'Could not load documents', '暫時無法讀取文件':'Your library is temporarily unavailable',
  '確認服務正在執行後，按搜尋重新載入。':'Check that the local server is running, then search again.',
  '無法連線，請確認本機服務正在執行。':'Could not connect. Check that the local server is running.',
  '匯入未完成，請確認連線後再試。已成功的文件再次匯入時會自動略過。':'Import did not finish. Check your connection and try again. Files already imported will be skipped.',
  '僅支援 .txt 與 .md 檔案。':'Only .txt and .md files are supported.',
  '檔案超過 5 MB 上限。':'The file exceeds the 5 MB limit.',
  '無法以 UTF-8 讀取；請先另存為 UTF-8 編碼。':'Cannot read this file as UTF-8. Save it with UTF-8 encoding first.',
  '檔案含有二進位或不支援的文字內容。':'The file contains binary or unsupported text content.',
  '檔案沒有可搜尋的文字。':'The file contains no searchable text.',
  '已加入文件庫':'Added to your library', '內容相同，已略過':'Identical content; skipped',
  '不接受跨來源的修改請求。':'Changes from another origin are not allowed.',
  '查詢不能含有 NUL 字元。':'Search queries cannot contain NUL characters.',
  '找不到這份文件。':'Document not found.',
  '請求失敗（{status}），請稍後再試。':'Request failed ({status}). Please try again.',
  '{date} 匯入':'Imported {date}', '預覽 {title}':'Preview {title}',
  '{total} 份文件 · {ms} ms':'{total} documents · {ms} ms',
  '正在匯入 {count} 份文件…':'Importing {count} files…',
  '匯入完成 · 新增 {imported} 份 / 共 {total} 份':'Import complete · {imported} added / {total} files',
};
let language = 'zh';
try { if (localStorage.getItem('papertrail-language') === 'en') language = 'en'; } catch {}
function t(key, values = {}) {
  const template = language === 'en' ? (EN[key] || key) : key;
  return template.replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? `{${name}}`));
}

// Capture only the initial UI nodes, before documents or server results are rendered.
const staticText = [];
const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
while (walker.nextNode()) {
  const node = walker.currentNode;
  if (node.parentElement.closest('script, style, #language-select')) continue;
  const key = node.textContent.trim();
  if (Object.hasOwn(EN, key)) staticText.push({node, key, original:node.textContent});
}
const staticAttributes = [];
for (const node of document.querySelectorAll('[aria-label], [placeholder]')) {
  for (const attribute of ['aria-label', 'placeholder']) {
    const key = node.getAttribute(attribute);
    if (key && Object.hasOwn(EN, key)) staticAttributes.push({node, attribute, key});
  }
}
function applyLanguage() {
  document.documentElement.lang = language === 'en' ? 'en' : 'zh-Hant';
  document.title = t('紙間 · 個人文件搜尋');
  for (const {node,key,original} of staticText) node.textContent = original.replace(key, t(key));
  for (const {node,attribute,key} of staticAttributes) node.setAttribute(attribute,t(key));
  document.querySelector('#language-select').value = language;
}
document.querySelector('#language-select').addEventListener('change', event => {
  language = event.target.value === 'en' ? 'en' : 'zh';
  try { localStorage.setItem('papertrail-language', language); } catch {}
  applyLanguage();
  document.dispatchEvent(new Event('languagechange'));
});
applyLanguage();
