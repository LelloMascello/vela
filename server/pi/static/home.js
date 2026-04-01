const userId = localStorage.getItem("user_id");

// Protezione rotta: se non loggato, reindirizza al login
if (!userId) {
    window.location.href = "/";
} else {
    document.getElementById("user-display").innerText = localStorage.getItem("username");
    // Avvia il caricamento iniziale
    loadChats();
}

function logout() {
    localStorage.clear();
    window.location.href = "/";
}

// --- Variabili di stato per Infinite Scroll ---
let skip = 0;
const limit = 10;
let isLoading = false;
let hasMore = true;

async function loadChats() {
    // Prevent overlapping calls or fetching when no more chats exist
    if (isLoading || !hasMore) return;
    
    isLoading = true;
    
    try {
        console.log(`Fetching chats for user ${userId} with skip=${skip}, limit=${limit}`);
        const response = await fetch(`/api/chats/${userId}?skip=${skip}&limit=${limit}`);
        
        // Check for backend errors (e.g., 500 or 422)
        if (!response.ok) {
            console.error("Server responded with an error:", response.status, await response.text());
            return;
        }

        const data = await response.json();
        console.log("Data received from server:", data);
        
        const container = document.getElementById("exchanges-list");

        // UI Feedback: If it's the very first load and the DB is completely empty
        if (skip === 0 && (!data.chats || data.chats.length === 0)) {
            container.innerHTML = "<p style='text-align:center; margin-top:20px; opacity:0.7;'>Nessuna conversazione trovata. Inizia una nuova chat!</p>";
            hasMore = false;
            return;
        }

        if (data.chats.length === 0) {
            hasMore = false;
            return;
        }

        if (data.chats.length < limit) {
            hasMore = false;
        }

        data.chats.forEach(session => {
            const card = document.createElement("div");
            card.className = "exchange-card";
            card.id = `chat-${session._id}`; 

            const cardHeader = document.createElement("div");
            cardHeader.style.display = "flex";
            cardHeader.style.justifyContent = "flex-end";
            cardHeader.style.marginBottom = "10px";
            
            const deleteBtn = document.createElement("button");
            deleteBtn.innerText = "Elimina";
            deleteBtn.className = "delete-btn"; 
            deleteBtn.onclick = () => deleteChat(session._id);
            
            cardHeader.appendChild(deleteBtn);
            card.appendChild(cardHeader);

            // SAFETY CHECK: Protect against old/malformed MongoDB documents
            if (session.exchanges && Array.isArray(session.exchanges)) {
                session.exchanges.forEach(exchange => {
                    const questionDiv = document.createElement("div");
                    questionDiv.className = "chat-bubble user-question";
                    questionDiv.innerText = exchange.question || "N/A";

                    const responseDiv = document.createElement("div");
                    responseDiv.className = "chat-bubble ai-response";
                    responseDiv.innerText = exchange.response || "N/A";

                    card.appendChild(questionDiv);
                    card.appendChild(responseDiv);
                });
            } else {
                // Fallback UI so the page doesn't crash
                const errorMsg = document.createElement("div");
                errorMsg.innerText = "[Errore: Formato chat obsoleto nel database]";
                errorMsg.style.color = "red";
                card.appendChild(errorMsg);
            }

            container.appendChild(card);
        });

        skip += limit;
        
    } catch (error) {
        console.error("Network or parsing error:", error);
    } finally {
        isLoading = false;
    }
}

async function deleteChat(chatId) {
    if (!confirm("Sei sicuro di voler eliminare questa chat?")) return;

    try {
        const response = await fetch(`/api/chats/${chatId}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            const card = document.getElementById(`chat-${chatId}`);
            if (card) {
                // Rimuovi dolcemente dal DOM
                card.style.transition = "opacity 0.4s ease";
                card.style.opacity = 0;
                setTimeout(() => {
                    card.remove();
                }, 400);
            }
        } else {
            console.error("Errore del server durante l'eliminazione");
            alert("Impossibile eliminare la chat.");
        }
    } catch (error) {
        console.error("Errore di rete durante l'eliminazione:", error);
    }
}

// Filtro locale lato client
function filterChats() {
    const query = document.getElementById("search-input").value.toLowerCase();
    const cards = document.getElementsByClassName("exchange-card");

    for (let i = 0; i < cards.length; i++) {
        // Usa il textContent dell'intera card per ignorare i tag HTML nascosti
        const text = cards[i].textContent.toLowerCase();
        cards[i].style.display = text.includes(query) ? "flex" : "none";
        
        // Mantieni la consistenza con la direction column (dipende dal tuo CSS)
        if (text.includes(query)) {
             cards[i].style.flexDirection = "column";
        }
    }
}

// Event Listener per l'Infinite Scroll
window.addEventListener('scroll', () => {
    const { scrollTop, scrollHeight, clientHeight } = document.documentElement;
    
    // Se l'utente arriva a 100px dalla fine della pagina, carica nuovi risultati
    if (scrollTop + clientHeight >= scrollHeight - 100) {
        loadChats();
    }
});