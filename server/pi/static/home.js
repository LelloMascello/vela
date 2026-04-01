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
    try {
        const response = await fetch('/api/chats'); // Adjust this URL if your endpoint is different
        if (!response.ok) throw new Error("Errore nel caricamento delle chat");
        
        const chats = await response.json();
        const container = document.getElementById('exchanges-list');
        container.innerHTML = ''; // Pulisce il contenitore

        // Loop through each chat SESSION
        chats.forEach(chat => {
            // Create ONE card for the whole session
            const card = document.createElement('div');
            card.className = 'exchange-card';

            // Loop through the messages (exchanges) inside this specific session
            chat.exchanges.forEach(exchange => {
                // Create user bubble
                const questionDiv = document.createElement('div');
                questionDiv.className = 'chat-bubble user-question';
                questionDiv.innerText = exchange.question;

                // Create AI bubble
                const responseDiv = document.createElement('div');
                responseDiv.className = 'chat-bubble ai-response';
                responseDiv.innerText = exchange.response;

                // Append both bubbles to the single card
                card.appendChild(questionDiv);
                card.appendChild(responseDiv);
            });

            // Append the finished card to the page
            container.appendChild(card);
        });
    } catch (error) {
        console.error(error);
    }
}

function filterChats() {
    const query = document.getElementById("search-input").value.toLowerCase();
    const cards = document.getElementsByClassName("exchange-card");

    for (let i = 0; i < cards.length; i++) {
        const text = cards[i].innerText.toLowerCase();
        cards[i].style.display = text.includes(query) ? "flex" : "none";
    }
}