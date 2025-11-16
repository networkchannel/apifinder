import os
import time
import random
import threading
from flask import Flask, jsonify, request
import requests

app = Flask(__name__)

# ==================== CONFIGURATION ====================
UNIVERSE_ID = "109983668079237"
MIN_PLAYERS = 2
COOLDOWN_SECONDS = 60
API_KEY = os.environ.get("API_KEY", os.environ.get("KEY", ""))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
]

# ==================== VARIABLES GLOBALES ====================
servers_cache = []
last_update = 0
next_update_allowed = 0
fetch_lock = threading.Lock()
is_fetching = False

# ==================== FONCTIONS ====================
def log(message):
    """Affiche un log avec timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

def fetch_servers():
    """Récupère tous les serveurs depuis l'API Roblox"""
    global servers_cache, last_update, next_update_allowed, is_fetching
    
    # Empêcher fetch simultanés
    if not fetch_lock.acquire(blocking=False):
        log("⏸️  Fetch déjà en cours, ignoré")
        return False
    
    try:
        is_fetching = True
        log("🔄 Début de la récupération des serveurs...")
        
        all_servers = []
        cursor = None
        page = 0
        
        while True:
            page += 1
            
            # Construction de l'URL
            url = f"https://games.roblox.com/v1/games/{UNIVERSE_ID}/servers/Public"
            params = {
                "sortOrder": "Desc",
                "excludeFullGames": "true",
                "limit": 100
            }
            if cursor:
                params["cursor"] = cursor
            
            try:
                # Requête HTTP
                headers = {
                    "User-Agent": random.choice(USER_AGENTS),
                    "Accept": "application/json"
                }
                
                response = requests.get(url, params=params, headers=headers, timeout=15)
                
                # Gestion rate limit
                if response.status_code == 429:
                    log(f"⛔ Rate limit (429) - Cache actuel: {len(all_servers)} serveurs")
                    if all_servers:
                        servers_cache = all_servers
                        last_update = time.time()
                    next_update_allowed = time.time() + COOLDOWN_SECONDS
                    return len(all_servers) > 0
                
                # Erreur HTTP
                if response.status_code != 200:
                    log(f"❌ Erreur HTTP {response.status_code}")
                    next_update_allowed = time.time() + 10
                    return False
                
                # Parse JSON
                data = response.json()
                servers = data.get("data", [])
                
                # Filtrage des serveurs
                filtered = 0
                for server in servers:
                    if server.get("playing", 0) >= MIN_PLAYERS:
                        all_servers.append({
                            "id": server.get("id"),
                            "playing": server.get("playing"),
                            "maxPlayers": server.get("maxPlayers")
                        })
                        filtered += 1
                
                log(f"📄 Page {page}: {len(servers)} serveurs, {filtered} gardés (>= {MIN_PLAYERS} joueurs)")
                
                # Vérifier s'il y a d'autres pages
                cursor = data.get("nextPageCursor")
                if not cursor:
                    break
                
                # Pause entre les pages
                time.sleep(random.uniform(0.5, 1.0))
                
            except requests.Timeout:
                log(f"⏱️  Timeout page {page}")
                break
            except requests.RequestException as e:
                log(f"❌ Erreur réseau: {str(e)[:100]}")
                break
            except Exception as e:
                log(f"❌ Erreur inattendue: {str(e)[:100]}")
                break
        
        # Mise à jour du cache
        if all_servers:
            servers_cache = all_servers
            last_update = time.time()
            next_update_allowed = time.time() + COOLDOWN_SECONDS
            log(f"✅ {len(all_servers)} serveurs en cache - Prochain fetch dans {COOLDOWN_SECONDS}s")
            return True
        else:
            log(f"⚠️  Aucun serveur trouvé (MIN_PLAYERS={MIN_PLAYERS})")
            next_update_allowed = time.time() + 10
            return False
            
    finally:
        is_fetching = False
        fetch_lock.release()

def start_background_fetch():
    """Lance un fetch en arrière-plan si nécessaire"""
    if time.time() < next_update_allowed:
        return
    
    if is_fetching:
        return
    
    thread = threading.Thread(target=fetch_servers, daemon=True)
    thread.start()

def check_api_key():
    """Vérifie la clé API"""
    if not API_KEY:
        return True
    
    key = request.args.get("key") or request.headers.get("X-API-Key")
    return key == API_KEY

# ==================== ROUTES ====================
@app.route("/")
def home():
    return jsonify({
        "name": "Roblox Server Finder API",
        "status": "online",
        "version": "2.0",
        "endpoints": {
            "/get_jobs": "Récupère la liste des serveurs",
            "/status": "Statut du service",
            "/force_update": "Force une mise à jour (admin)"
        }
    })

@app.route("/get_jobs")
def get_jobs():
    if not check_api_key():
        return jsonify({
            "status": "error",
            "message": "Clé API invalide"
        }), 403
    
    # Lancer un fetch si nécessaire
    start_background_fetch()
    
    # Calculer le temps avant prochain fetch
    time_until_next = max(0, int(next_update_allowed - time.time()))
    
    # Mélanger les serveurs pour l'équité
    shuffled = servers_cache.copy()
    random.shuffle(shuffled)
    
    return jsonify({
        "status": "ok",
        "servers_count": len(shuffled),
        "servers": shuffled,
        "cooldown_remaining": time_until_next,
        "is_updating": is_fetching,
        "last_update": int(last_update) if last_update > 0 else None
    })

@app.route("/status")
def status():
    return jsonify({
        "status": "online",
        "config": {
            "universe_id": UNIVERSE_ID,
            "min_players": MIN_PLAYERS,
            "cooldown_seconds": COOLDOWN_SECONDS
        },
        "cache": {
            "servers_count": len(servers_cache),
            "last_update": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_update)) if last_update > 0 else None,
            "seconds_ago": int(time.time() - last_update) if last_update > 0 else None
        },
        "fetch": {
            "is_fetching": is_fetching,
            "next_allowed": time.strftime("%H:%M:%S", time.localtime(next_update_allowed)) if next_update_allowed > 0 else None,
            "seconds_until_next": max(0, int(next_update_allowed - time.time()))
        }
    })

@app.route("/force_update")
def force_update():
    if not check_api_key():
        return jsonify({"status": "error", "message": "Clé API invalide"}), 403
    
    global next_update_allowed
    next_update_allowed = 0
    
    success = fetch_servers()
    
    return jsonify({
        "status": "success" if success else "error",
        "servers_count": len(servers_cache),
        "message": f"Fetch {'réussi' if success else 'échoué'}"
    })

# ==================== DÉMARRAGE ====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    
    log("=" * 50)
    log("🚀 Roblox Server Finder API v2.0")
    log("=" * 50)
    log(f"📡 Universe ID: {UNIVERSE_ID}")
    log(f"👥 Min Players: {MIN_PLAYERS}")
    log(f"⏱️  Cooldown: {COOLDOWN_SECONDS}s")
    log(f"🔑 API Key: {'✅ Configurée' if API_KEY else '❌ Aucune (mode ouvert)'}")
    log(f"🌐 Port: {port}")
    log("=" * 50)
    
    # Fetch initial
    log("🔄 Fetch initial...")
    if fetch_servers():
        log(f"✅ {len(servers_cache)} serveurs en cache")
    else:
        log("⚠️  Fetch initial échoué, retry automatique au premier appel")
    
    log("=" * 50)
    log("✅ Serveur prêt !")
    
    app.run(host="0.0.0.0", port=port, debug=False)
