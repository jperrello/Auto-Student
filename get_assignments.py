

import os
from dotenv import load_dotenv
from canvasapi import Canvas
from bs4 import BeautifulSoup
import re
import openai
from openai import OpenAI

#added for line: file_response = requests.get(attachment.url, allow_redirects=True)
import requests


load_dotenv()

CANVAS_API_KEY = os.getenv("CANVAS_CANVAS_API_KEY")

CANVAS_API_URL = os.getenv("CANVAS_CANVAS_API_URL")

# .env file stuff
openai_api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
openai_api_model_name = os.getenv("OPENAI_API_MODEL_NAME", "gpt-4o")


openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("Please add your OpenAI API key to the .env file.")

# OpenAI API
client = OpenAI(api_key=openai_api_key, base_url=openai_api_base)

if not CANVAS_API_URL or not CANVAS_API_KEY:
    raise ValueError("Missing Canvas API credentials in environment variables")

# Canvas API
canvas = Canvas(CANVAS_API_URL, CANVAS_API_KEY)

course = canvas.get_course(os.getenv("COURSE_ID"))


# Get assignments for this course
assignments = course.get_assignments()

def extract_text_from_html(html):
    """Extract plain text from HTML assignment descriptions."""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text()

def load_file_content(file_path):
    """Read file content as text (handles txt or similar)."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

for assignment in assignments:
    print(f"Processing: {assignment.name}")
    description_text = extract_text_from_html(assignment.description)

    file_contents = ""
    if hasattr(assignment, 'attachments') and assignment.attachments:
        for attachment in assignment.attachments:
            file_response = requests.get(attachment.url, allow_redirects=True)
            filename = attachment.filename
            with open(filename, 'wb') as file:
                file.write(file_response.content)
            print(f"Downloaded: {filename}")
            
            try:
                # Load file contents if it's a readable file
                file_contents += f"\n\n[Content of {filename}]\n"
                file_contents += load_file_content(filename)
            except Exception as e:
                print(f"Could not read {filename}: {e}")

    # LLM Prompt - needs work
    prompt = f"""
You are a helpful assistant. Here is an assignment:

[Assignment Description]
{description_text}

[Attached Files]
{file_contents}

Please provide the best possible answer.
"""

    print(f"Sending to LLM:\n{prompt[:500]}...\n")

    response = client.chat.completions.create(
        model=openai_api_model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )

    answer = response.choices[0].message.content.strip()
    print(f"LLM Response:\n{answer[:500]}...\n")
