// ═══════════════════════════════════════════════════════════════════════════
//  AUTH GUARD
// ═══════════════════════════════════════════════════════════════════════════

const _username = sessionStorage.getItem('username');
if (!_username) window.location.href = '/';

document.getElementById('header-username').textContent = _username || '';

function logout() {
  sessionStorage.removeItem('username');
  sessionStorage.removeItem('password');
  window.location.href = '/';
}

// ═══════════════════════════════════════════════════════════════════════════
//  DATA
// ═══════════════════════════════════════════════════════════════════════════

let allChats      = [];   // raw session docs from server
let filteredChats = [];   // after fuzzy search

// ═══════════════════════════════════════════════════════════════════════════
//  DATA HELPERS
//
//  Each document from /chats/select looks like:
//    { _id, username, created_at (unix ms), chat: [{role, content}, …] }
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Return the first assistant message in a session, or a fallback string.
 */
function sessionTitle(doc) {
  const msgs = doc.chat || [];
  const first = msgs.find(m => m.role === 'assistant');
  if (first && first.content) return first.content.slice(0, 60) + (first.content.length > 60 ? '…' : '');
  return 'Voice session';
}

/**
 * Return the last meaningful message text for the preview line.
 */
function previewText(doc) {
  const msgs = doc.chat || [];
  if (!msgs.length) return 'No messages';
  const last = msgs[msgs.length - 1];
  const text = last.content || '';
  return text.slice(0, 140) || 'No messages';
}

/**
 * Build a single searchable string from a session document.
 */
function chatToSearchString(doc) {
  const parts = [];
  if (doc.username) parts.push(doc.username);
  (doc.chat || []).forEach(m => { if (m.content) parts.push(m.content); });
  return parts.join(' ');
}

// ═══════════════════════════════════════════════════════════════════════════
//  FUZZY SEARCH
// ═══════════════════════════════════════════════════════════════════════════

function fuzzyScore(text, pattern) {
  if (!pattern) return 1;
  text    = text.toLowerCase();
  pattern = pattern.toLowerCase();

  if (text.includes(pattern)) return 1000 - text.indexOf(pattern);

  let score      = 0;
  let pi         = 0;
  let consecutive = 0;
  let lastMatch  = -1;

  for (let ti = 0; ti < text.length && pi < pattern.length; ti++) {
    if (text[ti] === pattern[pi]) {
      consecutive++;
      score += consecutive * 2 + (lastMatch === ti - 1 ? 4 : 0);
      if (ti === 0 || text[ti - 1] === ' ' || text[ti - 1] === '_') score += 6;
      lastMatch = ti;
      pi++;
    } else {
      consecutive = 0;
    }
  }

  return pi === pattern.length ? score : 0;
}

function fuzzyFilter(chats, query) {
  if (!query.trim()) return chats.map(c => ({ chat: c, score: 1 }));
  return chats
    .map(c => ({ chat: c, score: fuzzyScore(chatToSearchString(c), query.trim()) }))
    .filter(r => r.score > 0)
    .sort((a, b) => b.score - a.score);
}

// ═══════════════════════════════════════════════════════════════════════════
//  HIGHLIGHT  — wrap matched characters in <mark>
// ═══════════════════════════════════════════════════════════════════════════

function highlight(text, pattern) {
  if (!pattern) return escHtml(text);
  const lower = text.toLowerCase();
  const pat   = pattern.toLowerCase();

  const idx = lower.indexOf(pat);
  if (idx !== -1) {
    return escHtml(text.slice(0, idx))
      + '<mark>' + escHtml(text.slice(idx, idx + pat.length)) + '</mark>'
      + escHtml(text.slice(idx + pat.length));
  }

  let result = '';
  let pi = 0;
  for (let ti = 0; ti < text.length; ti++) {
    if (pi < pat.length && lower[ti] === pat[pi]) {
      result += '<mark>' + escHtml(text[ti]) + '</mark>';
      pi++;
    } else {
      result += escHtml(text[ti]);
    }
  }
  return result;
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// ═══════════════════════════════════════════════════════════════════════════
//  RENDER
// ═══════════════════════════════════════════════════════════════════════════

function formatDate(doc) {
  // created_at is stored as unix ms by main.py
  const raw = doc.created_at;
  if (!raw) return '';
  // MongoDB BSON date serialised by bson json_util comes as {"$date": ...}
  const ms  = (typeof raw === 'object' && raw.$date) ? raw.$date : raw;
  const d   = new Date(ms);
  if (isNaN(d)) return '';
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
    + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function renderChats(results, query) {
  const list = document.getElementById('chats-list');

  if (!results.length) {
    list.innerHTML = `
      <div class="chats-empty">
        <span class="empty-icon">🔍</span>
        <p>${query ? `No sessions match "<strong>${escHtml(query)}</strong>"` : 'No sessions yet.'}</p>
      </div>`;
    return;
  }

  list.innerHTML = results.map(({ chat: doc }) => {
    const title   = sessionTitle(doc);
    const preview = previewText(doc);
    const date    = formatDate(doc);
    const msgs    = doc.chat || [];
    // Count only assistant turns as "AI replies"
    const aiCount = msgs.filter(m => m.role === 'assistant').length;

    return `
      <div class="chat-card">
        <div class="chat-card-header">
          <span class="chat-title">${highlight(title, query)}</span>
          <span class="chat-date">${escHtml(date)}</span>
        </div>
        <div class="chat-preview">${highlight(preview, query)}</div>
        <div class="chat-meta">
          <span class="chat-turns">${aiCount} AI response${aiCount !== 1 ? 's' : ''}</span>
        </div>
      </div>`;
  }).join('');

  document.getElementById('chats-count').textContent =
    results.length + ' of ' + allChats.length + ' session' + (allChats.length !== 1 ? 's' : '');
}

// ═══════════════════════════════════════════════════════════════════════════
//  SEARCH HANDLER
// ═══════════════════════════════════════════════════════════════════════════

function onSearch() {
  const query = document.getElementById('search-input').value;
  document.getElementById('search-clear').style.display = query ? 'inline-flex' : 'none';
  filteredChats = fuzzyFilter(allChats, query);
  renderChats(filteredChats, query);
}

function clearSearch() {
  document.getElementById('search-input').value = '';
  onSearch();
  document.getElementById('search-input').focus();
}

// ═══════════════════════════════════════════════════════════════════════════
//  LOAD CHATS
// ═══════════════════════════════════════════════════════════════════════════

async function loadChats() {
  try {
    const res = await fetch(`/chats/select?username=${encodeURIComponent(_username)}`);
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    allChats = await res.json();
    filteredChats = allChats;
    document.getElementById('chats-count').textContent =
      allChats.length + ' session' + (allChats.length !== 1 ? 's' : '');
    renderChats(filteredChats.map(c => ({ chat: c, score: 1 })), '');
  } catch (e) {
    document.getElementById('chats-list').innerHTML = `
      <div class="chats-empty">
        <span class="empty-icon">⚠️</span>
        <p>Failed to load sessions: ${escHtml(e.message)}</p>
      </div>`;
  }
}

// ── Init ──────────────────────────────────────────────────────────────────
loadChats();