import os
import requests
from plexapi.server import PlexServer
from datetime import datetime
import schedule
import time

# --- Configuration (Pulled from .env) ---
PLEX_URL = os.getenv('PLEX_URL')
PLEX_TOKEN = os.getenv('PLEX_TOKEN')
OLLAMA_URL = os.getenv('OLLAMA_URL')
LIBRARY_NAME = 'Movies'

def get_ai_decision(title, summary):
    """The 'Ruthless' System Prompt to filter out narrative and animated movies."""
    prompt = f"""
    You are a strict media analyst. Determine if the following title is a Stand-up Comedy Special.
    
    Title: {title}
    Summary: {summary}

    IMMEDIATELY REJECT (Return False) if:
    - It is ANIMATED or a cartoon (e.g., 'Kiff' or 'Lore of the Ring Light').
    - It is a narrative film, parody, or 'slapstick' movie with a cast playing characters (e.g., 'The Naked Gun').
    - The summary describes a plot, adventure, mission, or 'storyline'.
    - It features an ensemble cast or voice actors rather than one main comedian performing a set.

    ACCEPT (Return True) ONLY if:
    - It is a singular, live stage performance by a comedian (monologue/set).
    - The summary explicitly mentions 'on stage', 'live performance', or 'stand-up special'.

    Be extremely skeptical. Respond ONLY with 'True' or 'False'.
    """
    
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": "llama3",
            "prompt": prompt,
            "stream": False
        }, timeout=30)
        result = response.json().get('response', 'False').strip().lower()
        return 'true' in result
    except Exception as e:
        print(f"AI Error for {title}: {e}")
        return False

def run_scanner():
    print(f"[{datetime.now()}] Starting scan of {LIBRARY_NAME}...")
    try:
        if not PLEX_URL or not PLEX_TOKEN:
            print("Error: PLEX_URL or PLEX_TOKEN not found in environment.")
            return
            
        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        movies = plex.library.section(LIBRARY_NAME).search(genre="Comedy")
    except Exception as e:
        print(f"Connection Error: {e}")
        return

    for movie in movies:
        labels = [l.tag.lower() for l in movie.labels]
        
        # Conflict Resolution: If both tags exist, prioritize the negative one
        if 'verified_not_standup' in labels and 'standup' in labels:
            print(f"Conflict found for {movie.title}. Removing 'standup' tag.")
            movie.removeLabel('standup')
            continue
            
        if 'standup' in labels or 'verified_not_standup' in labels:
            continue

        print(f"Analyzing: {movie.title}")
        is_standup = get_ai_decision(movie.title, movie.summary)

        if is_standup:
            movie.addLabel('standup')
            print(f"  [+] TAGGED: {movie.title}")
        else:
            movie.addLabel('verified_not_standup')
            print(f"  [-] REJECTED: {movie.title}")

def schedule_task():
    try:
        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        m_hour = getattr(plex.settings, 'butlerEndHour', 5)
        run_at = f"{m_hour + 1:02d}:00"
        schedule.every().day.at(run_at).do(run_scanner)
        print(f"Scanner scheduled for {run_at} daily.")
    except:
        print("Schedule error. Retrying in 1 hour.")

if __name__ == "__main__":
    run_scanner()
    schedule_task()
    while True:
        schedule.run_pending()
        time.sleep(60)