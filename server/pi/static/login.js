async function accedi() {
    const u = document.getElementById("username").value;
    const p = document.getElementById("password").value;

    const response = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: p })
    });

    if (response.ok) {
        const data = await response.json();
        // Save user ID to local storage so home.html knows who is logged in
        localStorage.setItem("user_id", data.user_id);
        localStorage.setItem("username", data.username);
        window.location.href = "/home";
    } else {
        alert("Login fallito. Controlla le credenziali.");
    }
}