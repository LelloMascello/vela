async function signup() {
    const u = document.getElementById("username").value;
    const e = document.getElementById("email").value;
    const p = document.getElementById("password").value;
    const cp = document.getElementById("conferma_password").value;

    if (p !== cp) {
        alert("Le password non coincidono!");
        return;
    }

    const response = await fetch('/api/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, email: e, password: p })
    });

    if (response.ok) {
        alert("Registrazione completata! Ora puoi accedere.");
        window.location.href = "/";
    } else {
        const error = await response.json();
        alert("Errore: " + error.detail);
    }
}