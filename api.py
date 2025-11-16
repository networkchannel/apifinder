import os
import time
import random
import threading
from flask import Flask, jsonify, request
import requests

app = Flask(__name__)

# ================== CONFIG ==================
UNIVERSE_ID = "109983668079237"
MIN_PLAYERS = 2
API_URL_BASE = f"https://games.roblox.com/v1/games/{UNIVERSE_ID}/servers/Public?sortOrder=Desc&excludeFullGames=true&limit=100"

# durée de pause après un fetch complet (en secondes)
COOLDOWN_SECONDS = 60

API_KEY = os.environ.get("API_KEY", os.environ.get("KEY"))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
]

# ================== ETAT GLOBAL ==================
cache_data = []                # liste des serveurs (format dict)
last_fetch_time = 0            # timestamp du dernier fetch fini (ou 0)
cooldown_until = 0             # tant que time.time() < cooldown_until -> on n'appelle pas Roblox
fetching_lock = threading.Lock()
session = requests.Session()
initial_fetch_done = threading.Event()  # Pour attendre le premier fetch

# ================== UTIL ==================
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

def _fetch_all_pages_and_update_cache():
    """Récupère toutes les pages disponibles et met à jour cache_data.
       Si 429 reçu -> on stoppe et on met cooldown.
    """
    global cache_data, last_fetch_time, cooldown_until

    with fetching_lock:
        print("🔄 Début fetch complet (toutes les pages)...")
        collected = []
        next_cursor = None
        pages_fetched = 0

        while True:
            # Si on est tombé dans un cooldown externe (autre thread l'a mis), on interrompt proprement
            if time.time() < cooldown_until:
                print("⏸️ Cooldown détecté pendant le fetch — on stoppe le fetch pour éviter d'autres hits.")
                break

            url = API_URL_BASE
            if next_cursor:
                url += f"&cursor={next_cursor}"

            try:
                headers = make_headers()
                resp = session.get(url, headers=headers, timeout=15)

                # Gestion rate-limit : si 429 on met le cooldown et on arrête
                if resp.status_code == 429:
                    print("🚫 429 rate-limit détecté, on active cooldown d'1 minute et on stoppe le fetch.")
                    # Si on a déjà collecté des données, on les garde
                    if collected:
                        cache_data = collected
                        last_fetch_time = time.time()
                        print(f"✅ Cache partiel sauvegardé ({len(cache_data)} serveurs) avant cooldown.")
                    cooldown_until = time.time() + COOLDOWN_SECONDS
                    break

                resp.raise_for_status()
                data = resp.json()
                pages_fetched += 1

                for server in data.get("data", []):
                    playing = server.get("playing", 0)
                    if playing >= MIN_PLAYERS:
                        collected.append({
                            "id": server.get("id"),
                            "playing": playing,
                            "maxPlayers": server.get("maxPlayers", None)
                        })

                print(f"📄 Page {pages_fetched} récupérée : {len(data.get('data', []))} serveurs bruts, {len([s for s in data.get('data', []) if s.get('playing', 0) >= MIN_PLAYERS])} filtrés (>= {MIN_PLAYERS} joueurs)")

                next_cursor = data.get("nextPageCursor")
                if not next_cursor:
                    # toutes les pages récupérées
                    print("📦 Toutes les pages récupérées.")
                    break

                # petit délai aléatoire pour limiter risque de rate-limit
                time.sleep(random.uniform(0.5, 1.2))

            except requests.RequestException as e:
                # En cas d'erreur réseau, on arrête et on planifie un petit cooldown court
                print(f"⚠️ Erreur pendant fetch: {e}. Activation d'un court cooldown (10s).")
                # Sauvegarder ce qu'on a déjà si c'est mieux que rien
                if collected and len(collected) > len(cache_data):
                    cache_data = collected
                    last_fetch_time = time.time()
                    print(f"✅ Cache partiel sauvegardé ({len(cache_data)} serveurs) après erreur.")
                cooldown_until = time.time() + 10
                break
            except Exception as e:
                print(f"⚠️ Exception inattendue pendant fetch: {e}. Activation d'un court cooldown (10s).")
                if collected and len(collected) > len(cache_data):
                    cache_data = collected
                    last_fetch_time = time.time()
                    print(f"✅ Cache partiel sauvegardé ({len(cache_data)} serveurs) après exception.")
                cooldown_until = time.time() + 10
                break

        # Mettre à jour cache uniquement si on a au moins quelque chose
        if collected:
            cache_data = collected
            last_fetch_time = time.time()
            # après un fetch réussi -> cooldown d'1 minute
            cooldown_until = time.time() + COOLDOWN_SECONDS
            print(f"✅ Cache mis à jour ({len(cache_data)} serveurs). Cooldown jusqu'à {time.strftime('%H:%M:%S', time.localtime(cooldown_until))}.")
        else:
            print("⚠️ AUCUN serveur collecté pendant le fetch ! Vérifiez le MIN_PLAYERS ou l'API.")
        
        # Signaler que le premier fetch est terminé
        initial_fetch_done.set()

def maybe_start_fetch_in_background():
    """Démarre un thread de fetch si possible (pas en cooldown et pas déjà en cours)."""
    if time.time() < cooldown_until:
        # on est en cooldown -> ne pas fetch
        print("🕒 Cooldown actif, pas de nouveau fetch.")
        return

    # Si déjà en cours -> rien
    if fetching_lock.locked():
        print("🔒 Fetch déjà en cours, on n'en lance pas un autre.")
        return

    # Lancer thread de fetch
    th = threading.Thread(target=_fetch_all_pages_and_update_cache, daemon=True)
    th.start()
    print("🚀 Thread de fetch lancé en arrière-plan.")

def check_api_key(req: request) -> bool:
    if not API_KEY:
        return True  # Si pas de clé configurée, on accepte tout
    key = req.args.get("key") or req.headers.get("X-API-Key")
    return key == API_KEY

# ================== ROUTES ==================
@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "message": "✅ API Roblox Finder - En ligne",
        "cache_size": len(cache_data),
        "endpoints": {
            "/get_jobs": "Récupère la liste des serveurs (requiert API key)"
        }
    })

@app.route('/get_jobs')
def get_jobs():
    global cache_data, last_fetch_time, cooldown_until

    # auth
    if not check_api_key(request):
        return jsonify({"status": "error", "message": "⛔ Clé API invalide ou manquante."}), 403

    now = time.time()

    # Si le cache est vide et qu'aucun fetch n'est en cours, on attend le premier fetch
    if not cache_data and not initial_fetch_done.is_set():
        print("⏳ Premier appel avec cache vide, attente du fetch initial...")
        # Attendre max 15 secondes pour le premier fetch
        initial_fetch_done.wait(timeout=15)

    # Si on est en cooldown, on RENVOIE IMMÉDIATEMENT le cache (shuffle avant d'envoyer)
    if now < cooldown_until and cache_data:
        shuffled = cache_data.copy()
        random.shuffle(shuffled)
        return jsonify({
            "status": "cooldown",
            "cooldown_seconds_remaining": int(cooldown_until - now),
            "servers_loaded": len(shuffled),
            "servers": shuffled
        })

    # Si on n'est pas en cooldown :
    # - si cache vide -> lancer fetch en arrière-plan et renvoyer cache (vide ou partiel)
    # - si cache non vide -> on peut renvoyer cache shuffle et parallèlement tenter un fetch si aucune fetch en cours
    maybe_start_fetch_in_background()

    # renvoyer cache courant (randomisé) pour ne jamais bloquer
    shuffled = cache_data.copy()
    random.shuffle(shuffled)

    status = "updating" if fetching_lock.locked() or (now >= cooldown_until and now - last_fetch_time > COOLDOWN_SECONDS) else "ok"

    return jsonify({
        "status": status,
        "cooldown_seconds_remaining": max(0, int(cooldown_until - now)),
        "servers_loaded": len(shuffled),
        "servers": shuffled
    })

@app.route('/status')
def status():
    """Endpoint pour vérifier l'état du service"""
    now = time.time()
    return jsonify({
        "status": "online",
        "cache_size": len(cache_data),
        "min_players_filter": MIN_PLAYERS,
        "universe_id": UNIVERSE_ID,
        "last_fetch": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_fetch_time)) if last_fetch_time > 0 else None,
        "seconds_since_last_fetch": int(now - last_fetch_time) if last_fetch_time > 0 else None,
        "in_cooldown": now < cooldown_until,
        "cooldown_remaining": max(0, int(cooldown_until - now)),
        "fetch_in_progress": fetching_lock.locked(),
        "initial_fetch_completed": initial_fetch_done.is_set()
    })

# ================== LANCEMENT ==================
if __name__ == "__main__":
    print("🚀 Démarrage de l'API Roblox Finder...")
    
    # Lancer le premier fetch au démarrage
    print("🔄 Lancement du fetch initial...")
    threading.Thread(target=_fetch_all_pages_and_update_cache, daemon=True).start()
    
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 Serveur lancé sur le port {port}")
    print(f"📡 Universe ID: {UNIVERSE_ID}")
    print(f"🔑 API Key configurée: {'✅ Oui' if API_KEY else '⚠️ Non (mode ouvert)'}")
    
    app.run(host='0.0.0.0', port=port)
