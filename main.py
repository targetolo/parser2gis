import os
import sys
import uuid
import asyncio
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

RESULTS_DIR = Path("/tmp/parser_results")
RESULTS_DIR.mkdir(exist_ok=True)

class ParseRequest(BaseModel):
    url: str
    format: str = "xlsx"
    max_records: int = 1000

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/debug")
async def debug():
    import shutil, subprocess
    chromium = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    try:
        ver = subprocess.check_output([chromium, "--version"], stderr=subprocess.STDOUT).decode() if chromium else "not found"
    except Exception as e:
        ver = str(e)
    from parser_2gis.chrome.utils import locate_chrome_path
    located = locate_chrome_path()
    return {
        "which_chromium": chromium,
        "version": ver,
        "located_by_parser": located,
        "env_chromium_path": os.environ.get("CHROMIUM_PATH"),
    }

@app.post("/parse")
async def parse(req: ParseRequest):
    if not req.url.startswith("https://2gis.ru"):
        raise HTTPException(status_code=400, detail="Только ссылки с 2GIS")

    if req.format not in ["xlsx", "csv", "json"]:
        raise HTTPException(status_code=400, detail="Формат должен быть xlsx, csv или json")

    job_id = str(uuid.uuid4())
    output_path = RESULTS_DIR / f"{job_id}.{req.format}"

    args = [
        'parser-2gis',
        '-i', req.url,
        '-o', str(output_path),
        '-f', req.format,
        f'--parser.max-records={req.max_records}',
        '--chrome.binary_path=/usr/bin/chromium',
        '--chrome.headless=yes',
        '--chrome.disable-images=yes',
        '--parser.delay_between_clicks=1500',
        '--parser.skip-404-response=yes',
        '--parser.use-gc=yes',
        '--parser.gc-pages-interval=3',
    ]

     runner_code = (
        "import sys, parser_2gis.parser as p, os\n"
        "import pkgutil\n"
        "print([m.name for m in pkgutil.iter_modules(p.__path__)])\n"
        "print(p.__file__)\n"
    )

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", runner_code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Таймаут — уменьши лимит записей")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    stderr_text = stderr.decode("utf-8", errors="replace")
    stdout_text = stdout.decode("utf-8", errors="replace")

    if not output_path.exists():
        raise HTTPException(status_code=500, detail=f"Ошибка парсера: {stderr_text[-1000:]}")

    file_size = output_path.stat().st_size
    if file_size < 500:
        raise HTTPException(
            status_code=500,
            detail=f"Пустой файл. STDERR: {stderr_text[-1500:]} | STDOUT: {stdout_text[-500:]}"
        )

    return {"job_id": "debug", "format": req.format, "size": 0, "stderr": stderr_text, "stdout": stdout_text}

@app.get("/download/{job_id}/{fmt}")
async def download(job_id: str, fmt: str):
    if "/" in job_id or ".." in job_id:
        raise HTTPException(status_code=400, detail="Неверный ID")
    path = RESULTS_DIR / f"{job_id}.{fmt}"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден или уже удалён")

    media_types = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
        "json": "application/json",
    }
    return FileResponse(
        path,
        media_type=media_types.get(fmt, "application/octet-stream"),
        filename=f"2gis_result.{fmt}",
    )
