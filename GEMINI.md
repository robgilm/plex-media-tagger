# Gemini Project Context: plex-media-tagger

## Project Overview

This project contains a Python script designed to automate the organization of a Plex media library. Its primary function is to identify stand-up comedy specials and roasts within the "Movies" section and apply specific labels to them.

**Purpose:**
To automatically distinguish stand-up comedy specials from regular movies and tag them accordingly in Plex for better organization and management.

**Main Technologies:**
*   **Language:** Python 3.11
*   **Core Libraries:** `plexapi`, `requests`, `schedule`
*   **AI:** Ollama (specifically the `llama3` model) for media classification.
*   **Deployment:** Docker

**Architecture:**
The application consists of a single Python script (`rm_standup.py`) that acts as a long-running service.
1.  On startup, it performs an initial scan of the Plex library.
2.  It then schedules a daily scan, timed to run one hour after the Plex server's maintenance window (`butlerEndHour`) to avoid conflicts.
3.  For each movie in the "Comedy" genre, it queries a running Ollama instance to determine if the item is a stand-up special.
4.  Based on the AI's response, it applies one of two labels in Plex:
    *   `standup`: If identified as a stand-up special.
    *   `verified_not_standup`: If not a stand-up special, to prevent re-analysis on future runs.
The script is intended to be deployed as a Docker container.

## Building and Running

### Prerequisites
*   A running Plex Media Server.
*   A running Ollama instance with the `llama3` model pulled.
*   Docker (for containerized deployment).
*   Python 3.11 (for local development).

### Configuration
Configuration is managed via a `.env` file in the project root. Create this file with the following variables:

```
PLEX_URL=http://YOUR_PLEX_IP:32400
PLEX_TOKEN=YOUR_PLEX_TOKEN
OLLAMA_URL=http://YOUR_OLLAMA_IP:11434/api/generate
```

### Local Development
1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Run the script:**
    ```bash
    python rm_standup.py
    ```

### Docker Deployment
The recommended way to run this tool is via Docker.

1.  **Build the Docker image:**
    ```bash
    docker build -t standup-tagger .
    ```
2.  **Run the Docker container:**
    ```bash
    docker run -d --name standup-tagger --env-file .env --network host standup-tagger
    ```

## Development Conventions

*   **Configuration:** All secrets and environment-specific settings are managed through environment variables, loaded from a `.env` file locally.
*   **Tagging:** The script uses a binary tagging system (`standup` or `verified_not_standup`) to maintain state and avoid redundant processing. This is the primary mechanism for tracking the script's work.
*   **Scheduling:** The script includes its own scheduler (`schedule` library) to run as a "set it and forget it" service, intelligently avoiding conflicts with Plex's own maintenance tasks.
*   **Ecosystem:** The `README.md` suggests using the [Maintainerr](https://github.com/jorenn92/Maintainerr) tool in conjunction with this script to automatically manage the `standup` collection and delete content after a specified period.
