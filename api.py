import os
import time
import random
import threading
from flask import Flask, jsonify, request
import requests

app = Flask(__name__)

# ================== CONFIGURATION ==================
UNIVERSE_ID = "109983668079237"
MIN_PLAYERS = 2
CACHE_EXPIRATION = 60  # secondes
API_URL_BASE = f"https://games.roblox.com/v1/games/{UNIVERSE_ID}/servers/Public?sortOrder=Desc&excludeFullGames=true&limit=100"

# 🔑 Clé d’accès
API_KEY = os.environ.get("API_KEY", os.environ.get("KEY"))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
]

# ================== CACHE GLOBAL ==================
cache_data = []
cache_timestamp = 0
fetching_lock = threading.Lock()
last_fetch_success = True
last_error_time = 0

# ================== OUTILS ==================
def make_headers():
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
    """Récupère tous les serveurs, gère les rate-limits et met à jour le cache."""
    global cache_data, cache_timestamp, last_fetch_success, last_error_time

    with fetching_lock:
        print("🔄 Début de la récupération complète des serveurs Roblox...")
        servers_info = []
        next_page_cursor = None
        session = requests.Session()

        while True:
            url = API_URL_BASE
            if next_page_cursor:
                url += f"&cursor={next_page_cursor}"
            headers = make_headers()

            try:
                response = session.get(url, headers=headers, timeout=10)

                # 🧱 Gestion du rate-limit
                if response.status_code == 429:
                    print("🚫 Rate limit détecté → pause de 2 minutes 30 avant reprise.")
                    last_fetch_success = False
                    last_error_time = time.time()
                    time.sleep(150)
                    continue

                response.raise_for_status()
                data = response.json()

                # Extraction des serveurs valides
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

                time.sleep(random.uniform(0.5, 1.2))

            except Exception as e:
                print(f"⚠️ Erreur réseau ou API : {e}")
                time.sleep(3)
                break

        cache_data = servers_info
        cache_timestamp = time.time()
        last_fetch_success = True
        print(f"✅ {len(servers_info)} serveurs enregistrés dans le cache.")

# ================== SECURITE ==================
def check_api_key(req: request) -> bool:
    key = req.args.get("key") or req.headers.get("X-API-Key")
    return key == API_KEY

# ================== ROUTES ==================
@app.route('/')
def home():
    return "✅ API Roblox Finder - En ligne (sécurisée + cache)."

@app.route('/get_jobs')
def get_jobs():
    global cache_data, cache_timestamp, last_fetch_success, last_error_time

    if not check_api_key(request):
        return jsonify({"status": "error", "message": "⛔ Clé API invalide ou manquante."}), 403

    current_time = time.time()
    time_since_last_fetch = current_time - cache_timestamp

    # Si en rate-limit, on renvoie le cache actuel
    if not last_fetch_success and (current_time - last_error_time < 150):
        wait_remaining = int(150 - (current_time - last_error_time))
        print(f"🕒 Rate limit actif, envoi du cache (encore {wait_remaining}s d’attente).")
        return jsonify({
            "status": "rate_limited",
            "wait_seconds_remaining": wait_remaining,
            "servers_loaded": len(cache_data),
            "servers": cache_data
        })

    # Si cache encore valide
    if cache_data and time_since_last_fetch < CACHE_EXPIRATION:
        print(f"♻️ Cache valide (mis à jour il y a {int(time_since_last_fetch)}s).")
        return jsonify({
            "status": "cached",
            "cache_age_seconds": int(time_since_last_fetch),
            "servers_loaded": len(cache_data),
            "servers": cache_data
        })

    # Si on peut rafraîchir (pas en cours de fetch)
    if not fetching_lock.locked():
        threading.Thread(target=fetch_all_jobs, daemon=True).start()
        print("🚀 Lancement d’un thread de mise à jour du cache Roblox.")

    return jsonify({
        "status": "updating",
        "message": "Les serveurs sont en cours de mise à jour. Cache actuel renvoyé.",
        "servers_loaded": len(cache_data),
        "servers": cache_data
    })

# ================== LANCEMENT ==================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Serveur lancé sur le port {port}")
    print(f"🔐 Clé API actuelle : {API_KEY}")
    app.run(host='0.0.0.0', port=port)
