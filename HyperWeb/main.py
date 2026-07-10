import os
import asyncio
import uuid
import shutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi import Request
import yt_dlp

app = FastAPI(title="HyperDownloader Web")

# Setup templates and temporary storage
templates = Jinja2Templates(directory="templates")
DOWNLOAD_DIR = "/tmp/hyper_downloads" if os.name != "nt" else "hyper_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# We use this to silence the yt-dlp terminal spam on the server
class MuteLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass

@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    """Serves the main frontend dashboard."""
    return templates.TemplateResponse(request=request, name="index.html")

@app.websocket("/ws/download")
async def websocket_endpoint(websocket: WebSocket):
    """Handles the real-time WebSocket connection for progress updates."""
    await websocket.accept()
    
    try:
        # Wait for the user to send a URL
        data = await websocket.receive_json()
        target_url = data.get("url")
        
        if not target_url:
            await websocket.send_json({"status": "error", "message": "No URL provided."})
            return

        file_id = str(uuid.uuid4())[:8]
        await websocket.send_json({"status": "info", "message": "Analyzing streams..."})

        # --- YT-DLP HOOK TO WEBSOCKET ---
        def progress_hook(d):
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 1)
                downloaded = d.get('downloaded_bytes', 0)
                speed = d.get('speed', 0)
                
                # Send live telemetry to the browser!
                asyncio.run(websocket.send_json({
                    "status": "downloading",
                    "percentage": round((downloaded / total) * 100, 1),
                    "speed_mb": round((speed if speed else 0) / (1024 * 1024), 2)
                }))
            elif d['status'] == 'finished':
                asyncio.run(websocket.send_json({
                    "status": "info",
                    "message": "Finalizing and merging file..."
                }))

        # Run extraction in a separate thread so it doesn't block the web server
        loop = asyncio.get_event_loop()
        
        # Check if FFmpeg exists on the host machine
        has_ffmpeg = shutil.which("ffmpeg") is not None
        
        # Smart Format Selection:
        # If FFmpeg exists, grab 1080p/4K and merge. If not, grab the best pre-merged file (usually 720p).
        format_str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" if has_ffmpeg else "b"

        ydl_opts = {
            "format": format_str,
            "outtmpl": f"{DOWNLOAD_DIR}/{file_id}_%(title)s.%(ext)s",
            "quiet": True,
            "logger": MuteLogger(),
            "progress_hooks": [progress_hook],
            "extractor_args": {'youtube': ['player_client=tv,default']},
        }
        
        if not has_ffmpeg:
            print("⚠ FFmpeg not found. Falling back to pre-merged 720p streams.")

        def execute_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                return ydl.prepare_filename(info)

        await websocket.send_json({"status": "info", "message": "Igniting Download Engine..."})
        
        # Await the blocking download function safely
        final_file_path = await loop.run_in_executor(None, execute_download)
        filename = os.path.basename(final_file_path)

        # Tell the frontend it's done and give them the download link!
        await websocket.send_json({
            "status": "complete",
            "download_url": f"/download/{filename}",
            "filename": filename
        })

    except WebSocketDisconnect:
        print("Client disconnected.")
    except Exception as e:
        await websocket.send_json({"status": "error", "message": str(e)})

@app.get("/download/{filename}")
async def download_file(filename: str):
    """Serves the downloaded file from the server to the user's computer."""
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=filename, media_type='application/octet-stream')
    return {"error": "File not found or expired."}