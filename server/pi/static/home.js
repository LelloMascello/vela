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
    // Evita chiamate sovrapposte o chiamate inutili se non ci sono più chat
    if (isLoading || !hasMore) return;
    
    isLoading = true;
    
    try {
        const response = await fetch(`/api/chats/${userId}?skip=${skip}&limit=${limit}`);
        const data = await response.json();
        const container = document.getElementById("exchanges-list");

        // Se l'API restituisce un array vuoto, abbiamo raggiunto la fine
        if (data.chats.length === 0) {
            hasMore = false;
            isLoading = false;
            return;
        }

        // Se restituisce meno elementi del limite, non ce ne saranno altri da caricare al prossimo giro
        if (data.chats.length < limit) {
            hasMore = false;
        }

        data.chats.forEach(session => {
            // Crea la card principale
            const card = document.createElement("div");
            card.className = "exchange-card";
            card.id = `chat-${session._id}`; // Assegniamo un ID per facilitare la rimozione dal DOM

            // Header della card con pulsante elimina
            const cardHeader = document.createElement("div");
            cardHeader.style.display = "flex";
            cardHeader.style.justifyContent = "flex-end";
            cardHeader.style.marginBottom = "10px";
            
            const deleteBtn = document.createElement("button");
            deleteBtn.innerText = "Elimina";
            deleteBtn.className = "delete-btn"; // Aggiungi lo stile a questa classe nel tuo CSS
            deleteBtn.onclick = () => deleteChat(session._id);
            
            cardHeader.appendChild(deleteBtn);
            card.appendChild(cardHeader);

            // Popola i messaggi della sessione all'interno della stessa card
            session.exchanges.forEach(exchange => {
                const questionDiv = document.createElement("div");
                questionDiv.className = "chat-bubble user-question";
                questionDiv.innerText = exchange.question;

                const responseDiv = document.createElement("div");
                responseDiv.className = "chat-bubble ai-response";
                responseDiv.innerText = exchange.response;

                card.appendChild(questionDiv);
                card.appendChild(responseDiv);
            });

            container.appendChild(card);
        });

        // Incrementa lo skip per la prossima chiamata
        skip += limit;
        
    } catch (error) {
        console.error("Errore nel recupero delle chat:", error);
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