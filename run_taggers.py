import os
import requests
from plexapi.server import PlexServer
from datetime import datetime, timedelta
import schedule
import time
import argparse # Import argparse
import json # Import the json module

# --- Configuration (Pulled from .env) ---
PLEX_URL = os.getenv('PLEX_URL')
PLEX_TOKEN = os.getenv('PLEX_TOKEN')
OLLAMA_URL = os.getenv('OLLAMA_URL')
LIBRARY_NAME = 'Movies'

# --- Trakt API Configuration ---
TRAKT_API_BASE_URL = "https://api.trakt.tv"
TRAKT_LIST_OWNER_USERNAME = "ad76"
TRAKT_LIST_SLUG = "hallmark-christmas"
TRAKT_CACHE_FILE = "trakt_cache.json" # Local cache file for Trakt list

# --- Load Tagger Definitions from config.json ---
try:
    with open('config.json', 'r') as f:
        CONFIG_DATA = json.load(f)
    TAGGER_CONFIGS = CONFIG_DATA.get('tagger_configs', {})
    TRAKT_API_CONFIG = CONFIG_DATA.get('trakt_api', {})
except FileNotFoundError:
    print("Error: config.json not found. Please ensure it's in the same directory as the script.")
    TAGGER_CONFIGS = {} # Set to empty to prevent further errors
    TRAKT_API_CONFIG = {}
    exit(1)
except json.JSONDecodeError:
    print("Error: Invalid JSON in config.json. Please check its syntax.")
    TAGGER_CONFIGS = {}
    TRAKT_API_CONFIG = {}
    exit(1)


def get_ai_decision(title, summary, prompt_template):
    """Sends a request to the AI with a specific prompt."""
    prompt = prompt_template.format(title=title, summary=summary)
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": "llama3",
            "prompt": prompt,
            "stream": False
        }, timeout=45)
        result = response.json().get('response', 'False').strip().lower()
        return 'true' in result
    except Exception as e:
        print(f"AI Error for {title}: {e}")
        return False

def load_trakt_cache(cache_file, cache_lifetime_hours):
    """Loads Trakt movie identifiers from a local cache file if it's fresh."""
    try:
        with open(cache_file, 'r') as f:
            cache_data = json.load(f)
        
        cached_timestamp = datetime.fromisoformat(cache_data['timestamp'])
        
        if datetime.now() - cached_timestamp < timedelta(hours=cache_lifetime_hours):
            print(f"[{datetime.now()}] Loading Trakt list from cache ({cache_file})...")
            return set(cache_data['identifiers'])
        else:
            print(f"[{datetime.now()}] Trakt cache expired. Re-fetching...")
            return None
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        print(f"[{datetime.now()}] Trakt cache not found or invalid. Fetching anew...")
        return None

def save_trakt_cache(cache_file, identifiers):
    """Saves Trakt movie identifiers to a local cache file."""
    try:
        cache_data = {
            'timestamp': datetime.now().isoformat(),
            'identifiers': list(identifiers) # Convert set to list for JSON serialization
        }
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)
        print(f"[{datetime.now()}] Trakt list saved to cache ({cache_file}).")
    except Exception as e:
        print(f"[{datetime.now()}] Error saving Trakt cache: {e}")

def fetch_trakt_list_movies(client_id, list_owner, list_slug):
    """Fetches movie identifiers from a specified Trakt list with retry logic and caching."""
    if not client_id:
        print("Trakt Client ID not found in config.json. Skipping Trakt list fetch.")
        return set()

    cache_lifetime_hours = TRAKT_API_CONFIG.get('cache_lifetime_hours', 24)
    cached_identifiers = load_trakt_cache(TRAKT_CACHE_FILE, cache_lifetime_hours)
    if cached_identifiers is not None:
        return cached_identifiers

    print(f"[{datetime.now()}] Fetching Trakt list from API: {list_owner}/{list_slug}...")
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": client_id
    }
    url = f"{TRAKT_API_BASE_URL}/users/{list_owner}/lists/{list_slug}/items"

    retries = 3
    for i in range(retries):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            trakt_items = response.json()
            
            trakt_movie_identifiers = set()
            for item in trakt_items:
                if item.get('movie'):
                    movie = item['movie']
                    if 'imdb' in movie['ids'] and movie['ids']['imdb']:
                        trakt_movie_identifiers.add(movie['ids']['imdb'])
                    if 'tmdb' in movie['ids'] and movie['ids']['tmdb']:
                        trakt_movie_identifiers.add(str(movie['ids']['tmdb'])) # TMDB ID is int, convert to str
                    if movie.get('title'):
                        trakt_movie_identifiers.add(movie['title'].lower()) # Use lower for case-insensitive title matching
            print(f"[{datetime.now()}] Fetched {len(trakt_movie_identifiers)} unique identifiers from Trakt list.")
            save_trakt_cache(TRAKT_CACHE_FILE, trakt_movie_identifiers) # Save to cache
            return trakt_movie_identifiers
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                retry_after = int(e.response.headers.get("Retry-After", 5)) # Default to 5 seconds
                print(f"[{datetime.now()}] Trakt API rate limit hit. Retrying after {retry_after} seconds (Attempt {i+1}/{retries})...")
                time.sleep(retry_after)
            else:
                print(f"[{datetime.now()}] HTTP Error fetching Trakt list: {e} (Attempt {i+1}/{retries}).")
                if i < retries - 1:
                    time.sleep(5) # Fixed backoff for other HTTP errors
                else:
                    print(f"[{datetime.now()}] Failed to fetch Trakt list after {retries} attempts.")
                    return set()
        except requests.exceptions.RequestException as e:
            print(f"[{datetime.now()}] Request Error fetching Trakt list: {e} (Attempt {i+1}/{retries}).")
            if i < retries - 1:
                time.sleep(5) # Fixed backoff for other request errors
            else:
                print(f"[{datetime.now()}] Failed to fetch Trakt list after {retries} attempts.")
                return set()
    print(f"[{datetime.now()}] Failed to fetch Trakt list after {retries} attempts.")
    return set()

def run_scanner(config_name):
    """Runs the scanner for a specific tagger configuration."""
    config = TAGGER_CONFIGS.get(config_name)
    if not config:
        print(f"Error: Configuration for tagger '{config_name}' not found.")
        return
        
    add_label = config['add_label']
    reject_label = config['reject_label']
    
    print(f"[{datetime.now()}] Starting '{config_name}' scan of {LIBRARY_NAME}...")
    
    # --- Trakt List Integration ---
    trakt_movie_identifiers = set()
    if config_name == "sappy_christmas": # Only for sappy_christmas tagger
        trakt_client_id = TRAKT_API_CONFIG.get('client_id')
        trakt_movie_identifiers = fetch_trakt_list_movies(trakt_client_id, TRAKT_LIST_OWNER_USERNAME, TRAKT_LIST_SLUG)
    # --- End Trakt List Integration ---

    try:
        if not PLEX_URL or not PLEX_TOKEN:
            print("Error: PLEX_URL or PLEX_TOKEN not found in environment.")
            return
        
        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        genres_to_search = config.get('genres')
        if genres_to_search and len(genres_to_search) > 0: # Ensure it's not None AND not an empty list
            movies = plex.library.section(LIBRARY_NAME).search(genre=genres_to_search)
        else:
            movies = plex.library.section(LIBRARY_NAME).all() # Search all movies if no genre filter
    except Exception as e:
        print(f"Connection Error: {e}")
        return

    processed_movies = 0
    tagged_movies = 0
    rejected_movies = 0

    for movie in movies:
        processed_movies += 1
        labels = [l.tag.lower() for l in movie.labels]
        
        # Conflict Resolution: If both tags exist, prioritize the negative one
        if reject_label in labels and add_label in labels:
            print(f"Conflict found for {movie.title}. Removing '{add_label}' tag.")
            movie.removeLabel(add_label)
            continue
            
        if add_label in labels or reject_label in labels:
            continue

        # --- Trakt List Matching (Pre-AI) ---
        is_trakt_match = False
        if trakt_movie_identifiers:
            plex_movie_ids = {movie.title.lower()} # Always include title for matching
            # Safely get IMDb ID
            imdb_id = getattr(movie, 'imdbID', None)
            if imdb_id:
                plex_movie_ids.add(imdb_id)
            
            # Safely get TMDB ID
            tmdb_id = getattr(movie, 'tmdbId', None)
            if tmdb_id:
                plex_movie_ids.add(str(tmdb_id)) # Convert to string for consistent type
            
            if not trakt_movie_identifiers.isdisjoint(plex_movie_ids):
                is_trakt_match = True
                print(f"  [+] TRAKT MATCH (Pre-AI) for '{config_name}': {movie.title}")
                movie.addLabel(add_label)
                tagged_movies += 1
                continue # Skip AI analysis
        # --- End Trakt List Matching ---

        # --- End Trakt List Matching ---

        # --- Keyword Pre-AI Filter ---
        if config_name == "sappy_christmas" and not is_trakt_match:
            pre_ai_keywords = config.get('pre_ai_keywords', [])
            pre_ai_keyword_threshold = config.get('pre_ai_keyword_threshold', 1)
            
            if pre_ai_keywords: # Only apply if keywords are configured
                keyword_matches = 0
                search_text = (movie.title + " " + (movie.summary or "")).lower()
                for keyword in pre_ai_keywords:
                    if keyword.lower() in search_text:
                        keyword_matches += 1
                
                if keyword_matches < pre_ai_keyword_threshold:
                    print(f"  [-] KEYWORD REJECT (Pre-AI) for '{config_name}': {movie.title} (Matches: {keyword_matches}/{pre_ai_keyword_threshold})")
                    movie.addLabel(reject_label)
                    rejected_movies += 1
                    continue # Skip AI analysis
        # --- End Keyword Pre-AI Filter ---

        print(f"Analyzing '{config_name}': {movie.title}")
        is_match = get_ai_decision(movie.title, movie.summary, config['prompt'])

        if is_match:
            movie.addLabel(add_label)
            tagged_movies += 1
            print(f"  [+] TAGGED '{add_label}': {movie.title}")
        else:
            movie.addLabel(reject_label)
            rejected_movies += 1
            print(f"  [-] REJECTED '{reject_label}': {movie.title}")
    
    print(f"[{datetime.now()}] Finished '{config_name}' scan. Summary:")
    print(f"  - Processed: {processed_movies} movies")
    print(f"  - Tagged: {tagged_movies} movies")
    print(f"  - Rejected: {rejected_movies} movies")

def orchestrate_scans():
    """Runs all configured taggers sequentially."""
    print(f"[{datetime.now()}] Initiating orchestrated scan for all taggers...")
    for name in TAGGER_CONFIGS:
        run_scanner(name)
    print(f"[{datetime.now()}] All orchestrated scans complete.")

def reset_all_tags():
    """Resets all tags created by this script from the Plex library."""
    print(f"[{datetime.now()}] Initiating reset of all script-generated tags...")
    try:
        if not PLEX_URL or not PLEX_TOKEN:
            print("Error: PLEX_URL or PLEX_TOKEN not found in environment.")
            return

        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        # Collect all possible labels that this script might have added
        all_managed_labels = set()
        for config in TAGGER_CONFIGS.values():
            all_managed_labels.add(config['add_label'])
            all_managed_labels.add(config['reject_label'])
        
        print(f"Managed labels to reset: {', '.join(all_managed_labels)}")

        movies = plex.library.section(LIBRARY_NAME).all() # Get all movies
        
        for movie in movies:
            current_labels = [l.tag.lower() for l in movie.labels]
            labels_to_remove = []
            
            for managed_label in all_managed_labels:
                if managed_label in current_labels:
                    labels_to_remove.append(managed_label)
            
            if labels_to_remove:
                print(f"  Removing tags {', '.join(labels_to_remove)} from: {movie.title}")
                for label in labels_to_remove:
                    movie.removeLabel(label)
            
    except Exception as e:
        print(f"Error during tag reset: {e}")
        return
    print(f"[{datetime.now()}] All script-generated tags reset successfully.")

def schedule_master_task():
    """Schedules the master orchestration task."""
    try:
        if not TAGGER_CONFIGS:
            print("No tagger configurations found. Skipping scheduling.")
            return

        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        m_hour = getattr(plex.settings, 'butlerEndHour', 5)
        
        # Determine the earliest desired run time from configurations
        # This will be the single time the orchestrator function runs
        min_offset = min(config.get('schedule_offset_hours', 1) for config in TAGGER_CONFIGS.values())
        run_at = f"{m_hour + min_offset:02d}:00" 
        
        schedule.every().day.at(run_at).do(orchestrate_scans)
        print(f"All taggers orchestrated to run daily at {run_at}.")
            
    except Exception as e:
        print(f"Schedule error: {e}. Retrying in 1 hour.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plex Media Tagger and Scheduler.")
    parser.add_argument("--scan", action="store_true", help="Perform an immediate orchestrated scan and exit.")
    parser.add_argument("--reset", action="store_true", help="Reset all script-generated tags and exit.")
    args = parser.parse_args()

    if not TAGGER_CONFIGS:
        print("No tagger configurations loaded. Exiting.")
        exit(1)

    if args.scan:
        orchestrate_scans()
    elif args.reset:
        reset_all_tags()
    else:
        print("Starting long-running scheduler mode...")
        print("Initial orchestrated scan on startup.")
        orchestrate_scans() # Initial run on startup
        
        print("Scheduling daily orchestrated run.")
        schedule_master_task()
        
        while True:
            schedule.run_pending()
            time.sleep(60)

