# FluxVid backend

FastAPI service that wraps yt-dlp and FFmpeg. See the top-level README for full documentation.

    pip install -r requirements.txt
    cp .env.example .env
    uvicorn main:app --env-file .env --port 8000
