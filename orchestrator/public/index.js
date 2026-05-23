// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.form-section').forEach(s => s.classList.add('hidden'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.tab).classList.remove('hidden');
    setMessage('', '');
  });
});

function setMessage(text, type) {
  const el = document.getElementById('message');
  el.textContent = text;
  el.className = type;
}

async function post(url, username, password) {
  const body = new FormData();
  body.append('username', username);
  body.append('password', password);
  const res = await fetch(url, { method: 'POST', body });
  return [res.ok, await res.json()];
}

async function handleLogin() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  if (!username || !password) return setMessage('Fill in all fields.', 'error');
  const [ok, data] = await post('/login', username, password);
  if (ok) {
    // Store credentials for the session (needed by router /auth endpoint)
    sessionStorage.setItem('username', data.username);
    sessionStorage.setItem('password', password);
    window.location.href = '/home';
  } else {
    setMessage(data.error, 'error');
  }
}

async function handleSignup() {
  const username = document.getElementById('signup-username').value.trim();
  const password = document.getElementById('signup-password').value;
  if (!username || !password) return setMessage('Fill in all fields.', 'error');
  const [ok, data] = await post('/signup', username, password);
  ok ? setMessage(`Account created for ${data.username}! You can now log in.`, 'success')
     : setMessage(data.error, 'error');
}