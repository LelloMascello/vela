// --- 1. Variabili di stato per Infinite Scroll (DA METTERE IN CIMA) ---
let skip = 0;
const limit = 10;
let isLoading = false;
let hasMore = true;

const userId = localStorage.getItem("user_id");

// --- 2. Protezione rotta e Avvio ---
if (!userId) {
    window.location.href = "/";
} else {
    document.getElementById("user-display").innerText = localStorage.getItem("username");
    // Ora possiamo chiamare loadChats perché isLoading è già stata inizializzata
    loadChats();
}

// --- 3. Funzioni ---
function logout() {
    localStorage.clear();
    window.location.href = "/";
}

async function loadChats() {
    if (isLoading || !hasMore) return;
    
    isLoading = true;
    
    try {
        console.log(`Fetching chats for user ${userId} with skip=${skip}, limit=${limit}`);
        const response = await fetch(`/api/chats/${userId}?skip=${skip}&limit=${limit}`);
        
        if (!response.ok) {
            console.error("Errore dal server:", response.status, await response.text());
            return;
        }

        const data = await response.json();
        console.log("Dati ricevuti:", data);
        
        const container = document.getElementById("exchanges-list");

        // Stato vuoto iniziale
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
                const errorMsg = document.createElement("div");
                errorMsg.innerText = "[Errore: Formato chat obsoleto nel database]";
                errorMsg.style.color = "red";
                card.appendChild(errorMsg);
            }

            container.appendChild(card);
        });

        skip += limit;
        
    } catch (error) {
        console.error("Errore di rete o di parsing:", error);
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

function filterChats() {
    const query = document.getElementById("search-input").value.toLowerCase();
    const cards = document.getElementsByClassName("exchange-card");

    for (let i = 0; i < cards.length; i++) {
        const text = cards[i].textContent.toLowerCase();
        cards[i].style.display = text.includes(query) ? "flex" : "none";
        
        if (text.includes(query)) {
             cards[i].style.flexDirection = "column";
        }
    }
}

// --- 4. Event Listeners ---
window.addEventListener('scroll', () => {
    const { scrollTop, scrollHeight, clientHeight } = document.documentElement;
    
    if (scrollTop + clientHeight >= scrollHeight - 100) {
        loadChats();
    }
});