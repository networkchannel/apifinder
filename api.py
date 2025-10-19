import os
import time
import random
from flask import Flask, jsonify, request
import requests

app = Flask(__name__)

# ================== CONFIGURATION ==================
UNIVERSE_ID = "109983668079237"
MIN_PLAYERS = 7
CACHE_EXPIRATION = 60  # Durée du cache en secondes
API_URL_BASE = f"https://games.roblox.com/v1/games/{UNIVERSE_ID}/servers/Public?sortOrder=Asc&limit=100"

# 🔑 Clé d’accès secrète (modifiable via variable d’environnement)
API_KEY = os.environ.get("API_KEY", os.environ.get("KEY"))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
]

# ================== CACHE GLOBAL ==================
cache_data = None
cache_timestamp = 0

# ================== OUTILS ==================
def make_headers():
    """Construit des en-têtes HTTP aléatoires pour éviter le rate-limit Roblox."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        "Referer": "https://www.roblox.com/",
        "Origin": "https://www.roblox.com",
        "DNT": "1"
    }

def fetch_all_jobs():
    """Récupère tous les serveurs publics avec leurs joueurs."""
    servers_info = []
    next_page_cursor = None
    session = requests.Session()

    while True:
        headers = make_headers()
        url_to_fetch = API_URL_BASE
        if next_page_cursor:
            url_to_fetch += f"&cursor={next_page_cursor}"

        try:
            response = session.get(url_to_fetch, headers=headers, timeout=8)
            response.raise_for_status()
            data = response.json()

            for server in data.get("data", []):
                playing = server.get("playing", 0)
                if playing >= MIN_PLAYERS:
                    servers_info.append({
                        "id": server.get("id"),
                        "playing": playing,
                        "maxPlayers": server.get("maxPlayers", None)
                    })

            next_page_cursor = data.get("nextPageCursor")
            if not next_page_cursor:
                break

            # Petit délai aléatoire pour éviter le rate-limit
            time.sleep(random.uniform(0.5, 1.2))

        except requests.RequestException as e:
            print(f"⚠️ Erreur lors du fetch : {e}")
            time.sleep(2)
            break

    return servers_info

# ================== SECURITE ==================
def check_api_key(req: request) -> bool:
    """Vérifie la clé d’API dans les headers ou la query string."""
    key = req.args.get("key") or req.headers.get("X-API-Key")
    return key == API_KEY

# ================== ROUTES ==================
@app.route('/')
def home():
    return "✅ API Roblox Finder - En ligne (sécurisée + cache)."

@app.route('/get_jobs')
def get_jobs():
    global cache_data, cache_timestamp

    # Vérification de la clé d’API
    if not check_api_key(request):
        return jsonify({"status": "error", "message": "⛔ Clé API invalide ou manquante."}), 403

    current_time = time.time()
    time_since_last_fetch = current_time - cache_timestamp

    # Utilisation du cache si valide
    if cache_data and time_since_last_fetch < CACHE_EXPIRATION:
        print(f"♻️ Réponse servie depuis le cache ({int(time_since_last_fetch)}s depuis la dernière mise à jour).")
        return jsonify({
            "status": "cached",
            "cache_age_seconds": int(time_since_last_fetch),
            "servers_loaded": len(cache_data),
            "servers": cache_data
        })

    # Sinon, nouvelle requête à Roblox
    print("🔄 Cache expiré ou vide → récupération depuis Roblox...")
    servers = fetch_all_jobs()
    cache_data = servers
    cache_timestamp = time.time()

    print(f"✅ {len(servers)} serveurs mis en cache.")
    return jsonify({
        "status": "fresh",
        "servers_loaded": len(servers),
        "servers": servers
    })

# ================== LANCEMENT ==================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Serveur lancé sur le port {port}")
    print(f"🔐 Clé API actuelle : {API_KEY}")
    app.run(host='0.0.0.0', port=port)
