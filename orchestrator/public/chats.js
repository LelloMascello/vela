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

let allChats     = [];   // raw chats from server
let filteredChats = [];  // after fuzzy search

// ═══════════════════════════════════════════════════════════════════════════
//  FUZZY SEARCH
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Score how well `pattern` matches `text`.
 * Returns a score >= 0: higher = better match, 0 = no match.
 * Uses a simple contiguous-subsequence approach that rewards
 * consecutive matching characters and start-of-word matches.
 */
function fuzzyScore(text, pattern) {
  if (!pattern) return 1;
  text    = text.toLowerCase();
  pattern = pattern.toLowerCase();

  // Exact substring is the best match
  if (text.includes(pattern)) return 1000 - text.indexOf(pattern);

  let score      = 0;
  let pi         = 0;       // position in pattern
  let consecutive = 0;
  let lastMatch  = -1;

  for (let ti = 0; ti < text.length && pi < pattern.length; ti++) {
    if (text[ti] === pattern[pi]) {
      consecutive++;
      // Reward consecutive chars and proximity
      score += consecutive * 2 + (lastMatch === ti - 1 ? 4 : 0);
      // Reward word-boundary matches
      if (ti === 0 || text[ti - 1] === ' ' || text[ti - 1] === '_') score += 6;
      lastMatch = ti;
      pi++;
    } else {
      consecutive = 0;
    }
  }

  // All pattern chars must appear in order
  return pi === pattern.length ? score : 0;
}

/**
 * Build a single searchable string from a chat document.
 * Searches over title, all message texts, and the username.
 */
function chatToSearchString(chat) {
  const parts = [];
  if (chat.title)    parts.push(chat.title);
  if (chat.username) parts.push(chat.username);
  if (Array.isArray(chat.messages)) {
    chat.messages.forEach(m => {
      if (m.text)    parts.push(m.text);
      if (m.content) parts.push(m.content);
    });
  }
  return parts.join(' ');
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
  const lower   = text.toLowerCase();
  const pat     = pattern.toLowerCase();

  // Exact substring highlight
  const idx = lower.indexOf(pat);
  if (idx !== -1) {
    return escHtml(text.slice(0, idx))
      + '<mark>' + escHtml(text.slice(idx, idx + pat.length)) + '</mark>'
      + escHtml(text.slice(idx + pat.length));
  }

  // Fuzzy character-level highlight
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

function formatDate(raw) {
  if (!raw) return '';
  const d = new Date(raw.$date ?? raw);
  if (isNaN(d)) return '';
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
       + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function previewText(chat) {
  if (!Array.isArray(chat.messages) || !chat.messages.length) return 'No messages';
  const last = chat.messages[chat.messages.length - 1];
  return (last.text || last.content || '').slice(0, 140) || 'No messages';
}

function renderChats(results, query) {
  const list = document.getElementById('chats-list');

  if (!results.length) {
    list.innerHTML = `
      <div class="chats-empty">
        <span class="empty-icon">🔍</span>
        <p>${query ? `No chats match "<strong>${escHtml(query)}</strong>"` : 'No chats yet.'}</p>
      </div>`;
    return;
  }

  list.innerHTML = results.map(({ chat }) => {
    const title   = chat.title || 'Untitled chat';
    const preview = previewText(chat);
    const date    = formatDate(chat.created_at);
    const count   = Array.isArray(chat.messages) ? chat.messages.length : 0;

    return `
      <div class="chat-card">
        <div class="chat-card-header">
          <span class="chat-title">${highlight(title, query)}</span>
          <span class="chat-date">${escHtml(date)}</span>
        </div>
        <div class="chat-preview">${highlight(preview, query)}</div>
        <div class="chat-meta">
          <span class="chat-turns">${count} message${count !== 1 ? 's' : ''}</span>
        </div>
      </div>`;
  }).join('');

  document.getElementById('chats-count').textContent =
    results.length + ' of ' + allChats.length + ' chat' + (allChats.length !== 1 ? 's' : '');
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
      allChats.length + ' chat' + (allChats.length !== 1 ? 's' : '');
    renderChats(filteredChats, '');
  } catch (e) {
    document.getElementById('chats-list').innerHTML = `
      <div class="chats-empty">
        <span class="empty-icon">⚠️</span>
        <p>Failed to load chats: ${escHtml(e.message)}</p>
      </div>`;
  }
}

// ── Init ──────────────────────────────────────────────────────────────────
loadChats();