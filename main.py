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
        '--chrome.headless=yes',
        '--chrome.silent-browser=yes',
        '--chrome.disable-images=yes',
        '--parser.delay_between_clicks=300',
        '--parser.skip-404-response=yes',
    ]

    # Patch Chrome to run with container-safe flags
    runner_code = f"""
import sys
import subprocess

sys.argv = {json.dumps(args)}

# Monkey-patch Chrome launch to add --no-sandbox
import parser_2gis.chrome.chrome as _chrome_mod
_orig_launch = _chrome_mod.Chrome._launch_chrome if hasattr(_chrome_mod, 'Chrome') else None

try:
    import parser_2gis.chrome.browser as _browser_mod
    _OrigBrowser = _browser_mod.Browser
    class _PatchedBrowser(_OrigBrowser):
        def _get_chrome_args(self, *a, **kw):
            args = super()._get_chrome_args(*a, **kw)
            extra = ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--single-process']
            return args + [x for x in extra if x not in args]
    _browser_mod.Browser = _PatchedBrowser
except Exception:
    pass

from parser_2gis.main import main
main()
"""

    env = {{
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "CHROMIUM_PATH": "/usr/bin/chromium",
    }}

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

    if not output_path.exists():
        raise HTTPException(status_code=500, detail=f"Ошибка парсера: {stderr_text[-1000:]}")

    file_size = output_path.stat().st_size
    if file_size < 500:
        raise HTTPException(
            status_code=500,
            detail="Парсер запустился, но не собрал данные — страница не успела загрузиться. Попробуй ещё раз."
        )

    return {"job_id": job_id, "format": req.format, "size": file_size}

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
