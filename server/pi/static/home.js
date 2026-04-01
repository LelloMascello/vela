const userId = localStorage.getItem("user_id");

// Protect route: if not logged in, boot back to login
if (!userId) {
    window.location.href = "/";
} else {
    document.getElementById("user-display").innerText = localStorage.getItem("username");
    loadChats();
}

function logout() {
    localStorage.clear();
    window.location.href = "/";
}

async function loadChats() {
    const response = await fetch(`/api/chats/${userId}`);
    const data = await response.json();
    const container = document.getElementById("exchanges-list");
    container.innerHTML = "";

    data.chats.forEach(session => {
        session.exchanges.forEach(exchange => {
            container.innerHTML += `
                <div class="exchange-card">
                    <div class="chat-bubble user-question">${exchange.question}</div>
                    <div class="chat-bubble ai-response">${exchange.response}</div>
                </div>
            `;
        });
    });
}

function filterChats() {
    const query = document.getElementById("search-input").value.toLowerCase();
    const cards = document.getElementsByClassName("exchange-card");

    for (let i = 0; i < cards.length; i++) {
        const text = cards[i].innerText.toLowerCase();
        cards[i].style.display = text.includes(query) ? "flex" : "none";
    }
}