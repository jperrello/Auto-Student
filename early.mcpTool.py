# assignment_tool.py

import os
import re
import html
import requests
from dotenv import load_dotenv
from canvasapi import Canvas
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional

# Load environment variables from .env
load_dotenv()
CANVAS_API_KEY = os.getenv("CANVAS_CANVAS_API_KEY")
CANVAS_API_URL = os.getenv("CANVAS_CANVAS_API_URL")
COURSE_ID = os.getenv("COURSE_ID")

# FastAPI app setup
app = FastAPI(
    title="Canvas Assignment Tool (No BeautifulSoup)",
    version="1.0.0",
    description="Fetches Canvas assignments, plain text only. Does not use BS4."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up Canvas
if not all([CANVAS_API_URL, CANVAS_API_KEY, COURSE_ID]):
    raise ValueError("Missing Canvas API config in .env")

canvas = Canvas(CANVAS_API_URL, CANVAS_API_KEY)
course = canvas.get_course(COURSE_ID)

# HTML stripping fallback (instead of bs4)
def strip_html_tags(raw_html: str) -> str:
    """Convert HTML to plain text using regex and html unescape."""
    clean_text = re.sub(r'<[^>]+>', '', raw_html or '')
    return html.unescape(clean_text)

def download_and_read_file(url: str, filename: str) -> str:
    try:
        r = requests.get(url)
        r.raise_for_status()
        with open(filename, 'wb') as f:
            f.write(r.content)
        with open(filename, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"[Error reading {filename}: {e}]"

# Models
class Attachment(BaseModel):
    filename: str
    content: Optional[str] = Field(None, description="File content if readable")

class AssignmentOut(BaseModel):
    id: int
    name: str
    due_at: Optional[str]
    description: Optional[str]
    attachments: Optional[List[Attachment]] = []

# API endpoint
@app.get("/assignments", response_model=List[AssignmentOut])
def get_assignments(limit: int = Query(10, description="Limit number of results")):
    """
    Fetch Canvas assignments as plain text (no HTML).
    Downloads and includes plain text file contents if present.
    """
    try:
        assignments = course.get_assignments()
        result = []

        for a in list(assignments)[:limit]:
            assignment_data = {
                "id": a.id,
                "name": a.name,
                "due_at": a.due_at,
                "description": strip_html_tags(a.description),
                "attachments": []
            }

            # Check & handle attachments
            if hasattr(a, 'attachments') and a.attachments:
                for att in a.attachments:
                    content = download_and_read_file(att.url, att.filename)
                    assignment_data["attachments"].append({
                        "filename": att.filename,
                        "content": content
                    })

            result.append(assignment_data)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch assignments: {e}")
