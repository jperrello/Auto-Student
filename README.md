# Auto-Student

A comprehensive academic assignment automation tool that integrates with Canvas LMS and OpenAI to automatically process and generate solutions for university assignments. USE THE jcasper BRANCH.

## Functionality (what it does)

Auto-Student consists of two main components:

### 1. Core Engine (`auto_student.py`)
- **Canvas Integration**: Automatically fetches courses and assignments from Canvas LMS
- **Content Extraction**: Downloads and processes linked files (HTML, text, documents)
- **YouTube Integration**: Extracts video IDs from assignments and fetches transcripts
- **Intelligent Summarization**: Automatically summarizes long content for context
- **AI-Powered Solutions**: Uses OpenAI models to generate comprehensive assignment answers
- **Reflective Questions**: Generates ethical reflection prompts before processing assignments

### 2. Web Interface (`slit.py`)
- **Streamlit Dashboard**: User-friendly web interface for assignment selection
- **Progress Tracking**: Real-time progress monitoring during processing
- **Ethical Safeguards**: Built-in plagiarism warnings and reflection questions
- **File Management**: Download generated prompts and solutions
- **Multi-Course Support**: Browse and select from multiple Canvas courses

## Installation

Install all required dependencies:

```bash
pip install asyncio logging pathlib dataclasses typing urllib aiofiles aiohttp beautifulsoup4 canvasapi openai pydantic-settings youtube-transcript-api streamlit pyperclip
```

## Configuration

Create a `.env` file in the project root with your API keys:

```env
CANVAS_API_KEY=your_canvas_api_key_here
CANVAS_API_URL=https://your-institution.instructure.com
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_API_BASE=https:/your_openai_base
SUMMARY_MODEL_NAME=google/gemma-3-4b-it
HW_MODEL_NAME=google/gemma-3-27b-it
```

## Usage

1. Set up your `.env` file with the required API keys
2. Run the Streamlit interface: `streamlit run slit.py`
3. Select your course and assignment from the web interface
4. Complete the reflective questions (ethical safeguard)
5. Process the assignment and download the generated solution

## Features

- Automatic content extraction from assignment descriptions
- YouTube transcript integration for video-based assignments  
- Multi-format file processing (HTML, text, JSON, etc.)
- AI-powered solution generation with context awareness
- Built-in plagiarism warnings and ethical reflection prompts
- Progress tracking and real-time status updates
- File download capabilities for prompts and solutions
