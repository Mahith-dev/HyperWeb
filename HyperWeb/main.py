import os
import asyncio
import uuid
import shutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
import yt_dlp

app = FastAPI(title="HyperDownloader Web")

# Setup templates and temporary cloud storage pathing
templates = Jinja2Templates(directory="templates")
DOWNLOAD_DIR = "/tmp/hyper_downloads" if os.name != "nt" else "hyper_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

class MuteLogger:
    """Gags yt-dlp internal background logs to keep the WebSocket traffic clean."""
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass

@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.websocket("/ws/download")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    try:
        data = await websocket.receive_json()
        target_url = data.get("url")
        
        if not target_url:
            await websocket.send_json({"status": "error", "message": "No asset URL detected."})
            return

        file_id = str(uuid.uuid4())[:8]
        await websocket.send_json({"status": "info", "message": "Parsing targeted media vectors..."})

        # --- STREAM LOGIC WEBSOCKET HOOK ---
        def progress_hook(d):
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 1)
                downloaded = d.get('downloaded_bytes', 0)
                speed = d.get('speed', 0)
                
                asyncio.run(websocket.send_json({
                    "status": "downloading",
                    "percentage": round((downloaded / total) * 100, 1),
                    "speed_mb": round((speed if speed else 0) / (1024 * 1024), 2)
                }))
            elif d['status'] == 'finished':
                asyncio.run(websocket.send_json({
                    "status": "info",
                    "message": "Finalizing and packaging asset container..."
                }))

        loop = asyncio.get_event_loop()
        
        # Check if system dependencies are active on the host
        has_ffmpeg = shutil.which("ffmpeg") is not None
        
        # Automated Extractor Routing: 
        # Spoofs a Safari agent over HLS vectors to seamlessly clean-pass datacenter bans
        extract_opts = {
            'quiet': True, 
            'no_warnings': True, 
            'logger': MuteLogger(),
            'extractor_args': {'youtube': ['player_client=web_safari']}
        }

        # Analyze stream meta configuration safely in a thread worker
        def fetch_meta():
            with yt_dlp.YoutubeDL(extract_opts) as ydl:
                return ydl.extract_info(target_url, download=False)

        info = await loop.run_in_executor(None, fetch_meta)
        clean_title = "".join([c for c in info['title'] if c.isalpha() or c.isdigit() or c in ' -_']).rstrip()

        # Build optimized high-performance format targets
        format_str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" if has_ffmpeg else "b"

        ydl_download_opts = {
            "format": format_str,
            "outtmpl": f"{DOWNLOAD_DIR}/{file_id}_{clean_title}.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "logger": MuteLogger(), 
            "continuedl": True,
            "overwrites": False,
            "socket_timeout": 30,
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": 3,
            "http_chunk_size": 10 * 1024 * 1024,
            "progress_hooks": [progress_hook],
            "extractor_args": {'youtube': ['player_client=web_safari']},
        }

        if has_ffmpeg:
            ydl_download_opts["ffmpeg_location"] = shutil.which("ffmpeg")
            ydl_download_opts["merge_output_format"] = "mp4"

        if shutil.which("aria2c"):
            ydl_download_opts["external_downloader"] = "aria2c"
            ydl_download_opts["external_downloader_args"] = [
                "-x4", "-s4", "-k1M", "--retry-wait=3", "--max-tries=20", "--summary-interval=0"
            ]

        def execute_download():
            with yt_dlp.YoutubeDL(ydl_download_opts) as ydl_dl:
                ydl_dl.download([target_url])
                return ydl_dl.prepare_filename(info)

        await websocket.send_json({"status": "info", "message": "Igniting Download Engine..."})
        
        # Process multi-threaded operational run
        final_file_path = await loop.run_in_executor(None, execute_download)
        filename = os.path.basename(final_file_path)

        await websocket.send_json({
            "status": "complete",
            "download_url": f"/download/{filename}",
            "filename": filename
        })

    except WebSocketDisconnect:
        print("Network worker connection dropped by remote user.")
    except Exception as e:
        await websocket.send_json({"status": "error", "message": str(e)})

@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=filename, media_type='application/octet-stream')
    return {"error": "Target resource expired or missing from cloud directory."}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
