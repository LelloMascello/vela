// ── Tab switching ─────────────────────────────────────────────────────────

document.querySelectorAll('.auth-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.form-section').forEach(s => s.classList.add('hidden'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.tab).classList.remove('hidden');
    setMessage('', '');
  });
});

// Allow Enter key on password inputs to submit

document.getElementById('login-password').addEventListener('keydown', e => {
  if (e.key === 'Enter') handleLogin();
});
document.getElementById('signup-password').addEventListener('keydown', e => {
  if (e.key === 'Enter') handleSignup();
});

// ── Helpers ───────────────────────────────────────────────────────────────

function setMessage(text, type) {
  const el = document.getElementById('message');
  el.textContent = text;
  el.className   = type || '';
}

async function post(url, username, password) {
  const body = new FormData();
  body.append('username', username);
  body.append('password', password);
  const res = await fetch(url, { method: 'POST', body });
  return [res.ok, await res.json()];
}

// ── Login ─────────────────────────────────────────────────────────────────

async function handleLogin() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  if (!username || !password) return setMessage('Please fill in all fields.', 'error');

  setMessage('Signing in…', '');
  const [ok, data] = await post('/login', username, password);
  if (ok) {
    sessionStorage.setItem('username', data.username);
    sessionStorage.setItem('password', password);
    window.location.href = '/home';
  } else {
    setMessage(data.error || 'Login failed.', 'error');
  }
}

// ── Sign up ───────────────────────────────────────────────────────────────

async function handleSignup() {
  const username = document.getElementById('signup-username').value.trim();
  const password = document.getElementById('signup-password').value;
  if (!username || !password) return setMessage('Please fill in all fields.', 'error');

  setMessage('Creating account…', '');
  const [ok, data] = await post('/signup', username, password);
  if (ok) {
    setMessage(`Account created for ${data.username}! You can now sign in.`, 'success');
  } else {
    setMessage(data.error || 'Sign-up failed.', 'error');
  }
}