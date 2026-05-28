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
//  DATA & PAGINATION
// ═══════════════════════════════════════════════════════════════════════════

let allChats      = [];
let filteredChats = [];
let currentPage   = 1;
const PAGE_SIZE   = 15;
let observer      = null;

// ═══════════════════════════════════════════════════════════════════════════
//  DATA HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function sessionTitle(doc) {
  const msgs = doc.chat || [];
  const first = msgs.find(m => m.role === 'user');
  if (first && first.content) {
    const text = first.content.trim();
    return text.length > 70 ? text.slice(0, 70) + '…' : text;
  }
  return 'Voice session';
}

function previewText(doc) {
  const msgs = doc.chat || [];
  if (!msgs.length) return 'No messages';
  const last = msgs[msgs.length - 1];
  const text = (last.content || '').trim();
  return text.length > 120 ? text.slice(0, 120) + '…' : text || 'No messages';
}

function chatToSearchString(doc) {
  const parts = [];
  if (doc.username) parts.push(doc.username);
  (doc.chat || []).forEach(m => { if (m.content) parts.push(m.content); });
  return parts.join(' ');
}

function formatDate(doc) {
  const raw = doc.created_at;
  if (!raw) return '';
  const ms = (typeof raw === 'object' && raw.$date) ? raw.$date : raw;
  const d  = new Date(ms);
  if (isNaN(d)) return '';
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
    + ' · '
    + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

// ═══════════════════════════════════════════════════════════════════════════
//  FUZZY SEARCH
// ═══════════════════════════════════════════════════════════════════════════

function fuzzyScore(text, pattern) {
  if (!pattern) return 1;
  text    = text.toLowerCase();
  pattern = pattern.toLowerCase();

  if (text.includes(pattern)) return 1000 - text.indexOf(pattern);

  let score = 0, pi = 0, consecutive = 0, lastMatch = -1;
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
//  HIGHLIGHT
// ═══════════════════════════════════════════════════════════════════════════

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

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

  let result = '', pi = 0;
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

// ═══════════════════════════════════════════════════════════════════════════
//  BUILD CHAT THREAD HTML
// ═══════════════════════════════════════════════════════════════════════════

function buildThreadHtml(doc, query) {
  const msgs = doc.chat || [];
  if (!msgs.length) {
    return '<div class="chats-empty" style="padding:1rem"><p>No messages in this session.</p></div>';
  }

  let html = '';
  for (const msg of msgs) {
    const isUser = msg.role === 'user';
    const role   = isUser ? 'You' : 'flow.ai';
    const cls    = isUser ? 'user-msg' : 'ai-msg';
    const text   = (msg.content || '').trim();
    if (!text) continue;

    html += `
      <div class="thread-turn">
        <div class="thread-role">${escHtml(role)}</div>
        <div class="thread-bubble ${cls}">${highlight(text, query)}</div>
      </div>`;
  }
  return html || '<div class="chats-empty" style="padding:1rem"><p>No messages in this session.</p></div>';
}

// ═══════════════════════════════════════════════════════════════════════════
//  RENDER SESSIONS (INFINITE SCROLL)
// ═══════════════════════════════════════════════════════════════════════════

function renderChats(reset = true, query = '') {
  const container = document.getElementById('chats-list-content');
  const sentinel  = document.getElementById('scroll-sentinel');

  if (reset) {
    currentPage = 1;
    container.innerHTML = '';
  }

  if (!filteredChats.length) {
    container.innerHTML = `
      <div class="chats-empty">
        <span class="empty-icon">🔍</span>
        <p>${query
          ? `No sessions match "<strong>${escHtml(query)}</strong>"`
          : 'No sessions yet. Start a voice session to see it here.'
        }</p>
      </div>`;
    if (sentinel) sentinel.style.display = 'none';
    return;
  }

  const startIndex = (currentPage - 1) * PAGE_SIZE;
  const endIndex   = startIndex + PAGE_SIZE;
  const slice      = filteredChats.slice(startIndex, endIndex);

  const html = slice.map(({ chat: doc }, indexOffset) => {
    const i        = startIndex + indexOffset; // Global index based on current slice
    const title    = sessionTitle(doc);
    const preview  = previewText(doc);
    const date     = formatDate(doc);
    const msgs     = doc.chat || [];
    const aiCount  = msgs.filter(m => m.role === 'assistant').length;
    const threadId = `thread-${i}`;

    return `
      <div class="chat-card" id="card-${i}" onclick="toggleCard(${i})">
        <div class="chat-card-header">
          <div class="chat-card-meta">
            <span class="chat-title">${highlight(title, query)}</span>
            <span class="chat-preview">${highlight(preview, query)}</span>
          </div>
          <div class="chat-card-right">
            <span class="chat-date">${escHtml(date)}</span>
            <span class="chat-badge">${aiCount} turn${aiCount !== 1 ? 's' : ''}</span>
            <span class="expand-icon">▾</span>
          </div>
        </div>
        <div class="chat-thread" id="${threadId}">
          ${buildThreadHtml(doc, query)}
        </div>
      </div>`;
  }).join('');

  if (reset) {
    container.innerHTML = html;
  } else {
    container.insertAdjacentHTML('beforeend', html);
  }

  document.getElementById('chats-count').textContent =
    filteredChats.length + ' of ' + allChats.length + ' session' + (allChats.length !== 1 ? 's' : '');

  // Toggle sentinel visibility
  if (sentinel) {
    sentinel.style.display = endIndex >= filteredChats.length ? 'none' : 'block';
  }
}

// ═══════════════════════════════════════════════════════════════════════════
//  INTERSECTION OBSERVER LOGIC
// ═══════════════════════════════════════════════════════════════════════════

function setupObserver() {
  const sentinel = document.getElementById('scroll-sentinel');
  if (!sentinel) return;

  observer = new IntersectionObserver((entries) => {
    // If the sentinel scrolls into view and there are still elements left to render
    if (entries[0].isIntersecting) {
      if (currentPage * PAGE_SIZE < filteredChats.length) {
        currentPage++;
        const currentQuery = document.getElementById('search-input').value;
        renderChats(false, currentQuery);
      }
    }
  }, { rootMargin: '200px' });

  observer.observe(sentinel);
}

// ═══════════════════════════════════════════════════════════════════════════
//  EXPAND / COLLAPSE
// ═══════════════════════════════════════════════════════════════════════════

function toggleCard(index) {
  const card = document.getElementById(`card-${index}`);
  if (!card) return;
  card.classList.toggle('expanded');
}

// ═══════════════════════════════════════════════════════════════════════════
//  SEARCH
// ═══════════════════════════════════════════════════════════════════════════

function onSearch() {
  const query = document.getElementById('search-input').value;
  document.getElementById('search-clear').style.display = query ? 'inline-flex' : 'none';
  filteredChats = fuzzyFilter(allChats, query);
  renderChats(true, query);
}

function clearSearch() {
  document.getElementById('search-input').value = '';
  onSearch();
  document.getElementById('search-input').focus();
}

// ═══════════════════════════════════════════════════════════════════════════
//  LOAD
// ═══════════════════════════════════════════════════════════════════════════

async function loadChats() {
  try {
    const res = await fetch(`/chats/select?username=${encodeURIComponent(_username)}`);
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    
    const rawChats = await res.json();
    
    // Store raw documents for searching
    allChats       = rawChats; 
    
    // Wrap them with scores for the initial UI render
    filteredChats  = allChats.map(c => ({ chat: c, score: 1 }));

    // Initial render and set up infinite scroll observer
    renderChats(true, '');
    setupObserver();

  } catch (e) {
    document.getElementById('chats-list-content').innerHTML = `
      <div class="chats-empty">
        <span class="empty-icon">⚠️</span>
        <p>Failed to load sessions: ${escHtml(e.message)}</p>
      </div>`;
  }
}

// ── Init ──────────────────────────────────────────────────────────────────
loadChats();