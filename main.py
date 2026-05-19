import os
import sys
import uuid
import asyncio
import subprocess
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
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

    cmd = [
        sys.executable, "-c",
        f"from parser_2gis.main import main; main()",
        "--",
        "-i", req.url,
        "-o", str(output_path),
        "-f", req.format,
        f"--parser.max-records={req.max_records}",
        "--chrome.headless=yes",
        "--chrome.silent-browser=yes",
        "--chrome.disable-images=yes",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Таймаут — слишком много данных, уменьши лимит записей")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not output_path.exists():
        error_msg = stderr.decode("utf-8", errors="replace")[-500:]
        raise HTTPException(status_code=500, detail=f"Парсер не смог создать файл: {error_msg}")

    return {"job_id": job_id, "format": req.format}

@app.get("/download/{job_id}/{fmt}")
async def download(job_id: str, fmt: str):
    # sanitize
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
