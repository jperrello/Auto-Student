import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any, Callable
from urllib.parse import urljoin, urlparse
import aiofiles
import aiohttp
from bs4 import BeautifulSoup
from canvasapi import Canvas
from openai import AsyncOpenAI
from pydantic_settings import BaseSettings
from pydantic import field_validator

from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable


class Settings(BaseSettings):
    OPENAI_API_KEY: str
    OPENAI_API_BASE: str
    CANVAS_API_KEY: str
    CANVAS_API_URL: str
    SUMMARY_MODEL_NAME: str
    HW_MODEL_NAME: str
    COURSE_ID: str
    max_file_size: int = 50 * 1024 * 1024
    download_timeout: int = 30

    @field_validator('COURSE_ID')
    def validate_COURSE_ID(cls, v):
        if not v or not v.isdigit():
            raise ValueError('Course ID must be a valid integer')
        return v

    class Config:
        env_file = ".env"

@dataclass
class AssignmentData:
    id: int
    name: str
    description: str
    links: List[str] = field(default_factory=list)
    youtube_video_ids: List[str] = field(default_factory=list)

def _extract_youtube_video_id(url: str) -> Optional[str]:
    if not isinstance(url, str):
        return None
    patterns = [
        r"(?:youtube\.com\/(?:watch\?(?:[^&]*&)*v=|embed\/|v\/|shorts\/|live\/))([a-zA-Z0-9_-]{11})",
        r"(?:youtu\.be\/)([a-zA-Z0-9_-]{11})",
        r"(?:googleusercontent\.com\/youtube\.com\/(?:watch\?(?:[^&]*&)*v=|embed\/|v\/))([a-zA-Z0-9_-]{11})",
        r"(?:youtube\.com\/.*[?&]v=)([a-zA-Z0-9_-]{11})",
        r"(?:googleusercontent\.com\/youtube\.com\/.*[?&]v=)([a-zA-Z0-9_-]{11})"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match and match.group(1):
            return match.group(1)
    return None

class AssignmentSolver:
    def __init__(self, settings: Settings, activity_callback: Optional[Callable[[str], None]] = None):
        self.settings = settings
        self.logger = self._setup_logging()
        self.session: Optional[aiohttp.ClientSession] = None
        self.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_API_BASE)
        self.canvas = Canvas(settings.CANVAS_API_URL, settings.CANVAS_API_KEY)
        self.downloads_dir = Path("downloads")
        self.downloads_dir.mkdir(exist_ok=True)
        self.activity_callback = activity_callback

    def _report_activity(self, description: str):
        if self.activity_callback:
            self.activity_callback(description)
        self.logger.info(description) #  logging for console/file fallback

    def _setup_logging(self) -> logging.Logger:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        return logging.getLogger(__name__)

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.settings.download_timeout)
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def test_canvas_connection(self) -> bool:
        self._report_activity("Attempting_Canvas_connection")
        try:
            user = await asyncio.to_thread(self.canvas.get_current_user)
            self._report_activity(f"Canvas_connection_successful_User_{user.name}")
            return True
        except Exception as e:
            self._report_activity(f"Canvas_connection_failed_{e}")
            self.logger.error(f"❌ Canvas connection failed: {e}")
            return False

    async def _summarize_text(self, text: str, max_words: int = 500) -> str:
        self._report_activity(f"Summarizing_text_length_{len(text)}")
        if not text or not text.strip():
            return "[No content to summarize]"
        if len(text.split()) <= max_words:
            return text
        prompt = f"Please summarize the following text in no more than {max_words} words, focusing on key points relevant to an academic assignment. Only provide me the summary as a block of text, I do not want you to repeat your task or ask me any follow up questions:\n\n{text[:10000]}"
        try:
            response = await self.openai_client.chat.completions.create(
                model=self.settings.SUMMARY_MODEL_NAME,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that summarizes academic materials concisely and accurately."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )
            summary = response.choices[0].message.content
            if not summary or not summary.strip():
                return f"[Empty summary returned for content of length {len(text)}]"
            self._report_activity(f"Summarized_text_successfully_length_{len(summary)}")
            return summary.strip()
        except Exception as e:
            self.logger.error(f"Error summarizing text (length: {len(text)}): {e}")
            words = text.split()
            return " ".join(words[:max_words]) + "... [truncated due to summarization error]" if len(words) > max_words else text

    def _extract_links_yt_from_html(self, html_content: str, base_url_for_links: str) -> Tuple[str, List[str], List[str]]:
        if not html_content or not html_content.strip():
            return "", [], []
        try:
            soup = BeautifulSoup(html_content, "html.parser")
        except Exception as e:
            self.logger.error(f"Failed to parse HTML: {e}")
            return "", [], []
        for unwanted in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'button', 'input', 'noscript']):
            unwanted.decompose()
        github_gist_selectors = ['.file-box .file-data', '.highlight', '.file .data', '.blob-code-content']
        general_selectors = ['article.user_content', 'div.user_content', 'div#content', 'main', 'div.content', 'div.assignment-description', '.markdown-body', '.post-content', '.entry-content']
        all_selectors = github_gist_selectors + general_selectors
        main_content_tag = None
        for selector in all_selectors:
            elements = soup.select(selector)
            if elements:
                if len(elements) == 1: main_content_tag = elements[0]
                else:
                    main_content_tag = soup.new_tag('div')
                    for elem in elements: main_content_tag.append(elem)
                break
        text_content = main_content_tag.get_text(separator='\n', strip=True) if main_content_tag else (soup.find('body') or soup).get_text(separator='\n', strip=True)
        cleaned_text = '\n'.join([line.strip() for line in text_content.split('\n') if line.strip()])
        general_links, youtube_video_ids = [], set()
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href')
            if not href or not isinstance(href, str) or href.startswith('#') or href.lower().startswith('javascript:'): continue
            video_id = _extract_youtube_video_id(href)
            if video_id: youtube_video_ids.add(video_id)
            else:
                try: general_links.append(urljoin(base_url_for_links, href))
                except Exception: self.logger.warning(f"Could not form absolute URL for link: {href}")
        for iframe in soup.find_all('iframe', src=True):
            src = iframe.get('src')
            if src and isinstance(src, str):
                video_id = _extract_youtube_video_id(src)
                if video_id: youtube_video_ids.add(video_id)
        return cleaned_text, list(general_links), list(youtube_video_ids)

    async def fetch_all_assignments(self) -> List[AssignmentData]:
        self._report_activity(f"Fetching_assignments_course_{self.settings.COURSE_ID}")
        try:
            course = await asyncio.to_thread(self.canvas.get_course, self.settings.COURSE_ID)
            assignments_raw = await asyncio.to_thread(list, course.get_assignments())
            structured_assignments = []
            for assign in assignments_raw:
                desc_html = getattr(assign, 'description', '') or ''
                cleaned_desc_text, general_links, yt_ids = self._extract_links_yt_from_html(desc_html, self.settings.CANVAS_API_URL)
                structured_assignments.append(AssignmentData(id=assign.id, name=assign.name, description=cleaned_desc_text, links=general_links, youtube_video_ids=yt_ids))
            self._report_activity(f"Fetched_{len(structured_assignments)}_assignments")
            return structured_assignments
        except Exception as e:
            self.logger.error(f"Failed to fetch assignments: {e}")
            self._report_activity(f"Failed_fetch_assignments_{e}")
            return []

    async def _get_youtube_transcript(self, video_id: str) -> Optional[str]:
        self._report_activity(f"Fetching_transcript_{video_id}")
        try:
            loop = asyncio.get_running_loop()
            transcript_list = await loop.run_in_executor(None, YouTubeTranscriptApi.get_transcript, video_id)
            transcript_text = " ".join([item['text'] for item in transcript_list])
            self._report_activity(f"Fetched_transcript_{video_id}_length_{len(transcript_text)}")
            summary = await self._summarize_text(transcript_text)
            self._report_activity(f"Summarized_transcript_{video_id}_length_{len(summary)}")
            return summary
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
            self.logger.warning(f"Transcript issue for {video_id}: {type(e).__name__}")
            self._report_activity(f"Transcript_issue_{video_id}_{type(e).__name__}")
            return f"[{type(e).__name__} for YouTube video ID: {video_id}]"
        except Exception as e:
            self.logger.error(f"Error fetching transcript for {video_id}: {str(e)}")
            self._report_activity(f"Error_transcript_{video_id}_{e}")
            return f"[Error fetching transcript for YouTube video ID: {video_id}: {str(e)}]"

    async def _download_file(self, url: str) -> Optional[Path]:
        if _extract_youtube_video_id(url) or url.startswith(('data:', 'mailto:')):
            self._report_activity(f"Skipping_download_{url[:50]}")
            return None
        self._report_activity(f"Downloading_{url}")
        try:
            async with self.session.get(url) as response:
                if response.status >= 400:
                    self.logger.error(f"HTTP {response.status} for {url}")
                    self._report_activity(f"Download_failed_HTTP_{response.status}_{url}")
                    return None
                content_type = response.headers.get('Content-Type', '').lower()
                filename = re.search(r'filename="?([^"]+)"?', response.headers.get('Content-Disposition',''))
                filename = filename.group(1) if filename else Path(urlparse(url).path).name or "downloaded_file"
                filename = re.sub(r'[^\w\-_\.]', '_', filename)
                if not Path(filename).suffix:
                    ext_map = {'html': '.html', 'json': '.json', 'text': '.txt'}
                    for key, ext in ext_map.items():
                        if key in content_type: filename += ext; break
                    else: filename += ".dat"
                filepath = self.downloads_dir / f"{int(time.time())}_{filename}"
                content_length = response.headers.get('Content-Length')
                if content_length and int(content_length) > self.settings.max_file_size:
                    self.logger.warning(f"File too large: {url}")
                    self._report_activity(f"Download_failed_too_large_{url}")
                    return None
                async with aiofiles.open(filepath, 'wb') as f:
                    downloaded_size = 0
                    async for chunk in response.content.iter_chunked(8192):
                        downloaded_size += len(chunk)
                        if downloaded_size > self.settings.max_file_size:
                            self.logger.warning(f"File exceeded max size: {url}")
                            self._report_activity(f"Download_failed_exceeded_size_{url}")
                            try: os.remove(filepath) # Try to clean up partial
                            except OSError: pass
                            return None
                        await f.write(chunk)
                self._report_activity(f"Downloaded_file_{filepath.name}_size_{downloaded_size}")
                return filepath
        except asyncio.TimeoutError: self.logger.error(f"Timeout downloading {url}"); self._report_activity(f"Download_timeout_{url}"); return None
        except aiohttp.ClientError as e: self.logger.error(f"Network error downloading {url}: {e}"); self._report_activity(f"Download_network_error_{url}"); return None
        except Exception as e: self.logger.error(f"Unexpected error downloading {url}: {e}"); self._report_activity(f"Download_unexpected_error_{url}"); return None

    async def _read_file_content(self, filepath: Path, original_url: str) -> str:
        if not filepath.exists(): return f"[File not found: {filepath}]"
        self._report_activity(f"Reading_file_{filepath.name}_url_{original_url}")
        file_size = filepath.stat().st_size
        if file_size == 0: return f"[Empty file: {filepath.name} from {original_url}]"
        file_extension = filepath.suffix.lower()
        try:
            if file_extension == '.html':
                async with aiofiles.open(filepath, 'r', encoding='utf-8', errors='replace') as f: html_content = await f.read()
                if not html_content.strip(): return f"[Empty HTML file: {filepath.name}]"
                self._report_activity(f"Processing_html_file_{filepath.name}_length_{len(html_content)}")
                cleaned_text, _, _ = self._extract_links_yt_from_html(html_content, original_url)
                if not cleaned_text.strip():
                     self.logger.warning(f"No text extracted from HTML: {filepath.name}. Raw HTML length: {len(html_content)}")
                     return f"[No text content extracted from HTML: {filepath.name}. Raw HTML length: {len(html_content)}]"
                self._report_activity(f"Extracted_text_from_html_{filepath.name}_length_{len(cleaned_text)}")
                summary = await self._summarize_text(cleaned_text)
                self._report_activity(f"Summarized_html_{filepath.name}_length_{len(summary)}")
                return summary
            elif file_extension in ['.txt', '.md', '.py', '.js', '.json', '.xml', '.css', '.csv', '.rtf']:
                async with aiofiles.open(filepath, 'r', encoding='utf-8', errors='replace') as f: content = await f.read()
                self._report_activity(f"Read_text_file_{filepath.name}_length_{len(content)}")
                # Text files usually don't need summarization unless very large,
                # but for consistency, we can summarize if it's above a threshold.
                # For now, return raw, but summarization can be added.
                # Let's assume for now it will be summarized by the main LLM prompt if needed.
                return content 
            elif file_extension == '.pdf': return f"[PDF File: {filepath.name} from {original_url} - PDF extraction not implemented]"
            elif file_extension in ['.doc', '.docx']: return f"[Word Document: {filepath.name} from {original_url} - Word extraction not implemented]"
            else: # Try to read as text, provide sample for unknown
                async with aiofiles.open(filepath, 'r', encoding='utf-8', errors='replace') as f: content_sample = await f.read(2048)
                return f"[Unknown file type content sample from {filepath.name}]:\n{content_sample}"
        except Exception as e:
            self.logger.error(f"Error reading/processing file {filepath.name}: {e}")
            self._report_activity(f"Error_reading_file_{filepath.name}_{e}")
            return f"[Error reading/processing file: {filepath.name} - {str(e)}]"

    async def generate_solution(self, assignment: AssignmentData) -> Dict[str, Any]:
        self._report_activity(f"Start_processing_assignment_{assignment.name}")
        initial_details_text = (
            f"Processing assignment: '{assignment.name}'\n"
            f"Description length: {len(assignment.description)}\n"
            f"Links found: {len(assignment.links)}\n"
            f"YouTube videos: {len(assignment.youtube_video_ids)}"
        )
        self._report_activity(f"Details_{assignment.name}_DescLen_{len(assignment.description)}_Links_{len(assignment.links)}_YT_{len(assignment.youtube_video_ids)}")

        supplementary_content_parts = []
        if assignment.links:
            async def process_single_link(url: str, index: int) -> Tuple[Optional[str], Optional[str], str]:
                filepath = await self._download_file(url)
                if not filepath: return None, f"[Download failed for: {url}]", url
                content = await self._read_file_content(filepath, url)
                filename = filepath.name
                # Clean up successful reads of summarizable/text files
                if content and not ("[Error" in content or "[No text content" in content or "not implemented]" in content or "Unknown file type" in content):
                    try: filepath.unlink()
                    except OSError as e: self.logger.warning(f"Could not delete temp file {filepath}: {e}")
                return filename, content, url
            link_tasks = [process_single_link(link, i) for i, link in enumerate(assignment.links)]
            link_results = await asyncio.gather(*link_tasks, return_exceptions=True)
            for i, result in enumerate(link_results):
                if isinstance(result, Exception): supplementary_content_parts.append(f"--- Error processing link {i+1}: {assignment.links[i]} ---\n[Exception: {result}]\n--- End Error ---")
                else:
                    filename, content, original_url = result
                    source_id = f"File: {filename} (from {original_url})" if filename else f"URL: {original_url}"
                    supplementary_content_parts.append(f"--- Content from {source_id} ---\n{content}\n--- End Content from {source_id} ---")
            self._report_activity(f"Processed_{len(assignment.links)}_links_for_{assignment.name}")

        if assignment.youtube_video_ids:
            transcript_tasks = [self._get_youtube_transcript(vid_id) for vid_id in assignment.youtube_video_ids]
            transcript_results = await asyncio.gather(*transcript_tasks, return_exceptions=True)
            for i, result in enumerate(transcript_results):
                video_id = assignment.youtube_video_ids[i]
                content = f"[Exception: {result}]" if isinstance(result, Exception) else (result or f"[No transcript for {video_id}]")
                supplementary_content_parts.append(f"--- YouTube Transcript (Video ID: {video_id}) ---\n{content}\n--- End Transcript (Video ID: {video_id}) ---")
            self._report_activity(f"Processed_{len(assignment.youtube_video_ids)}_youtube_videos_for_{assignment.name}")

        all_supplementary_content = "\n\n".join(supplementary_content_parts) if supplementary_content_parts else "[No supplementary content processed.]"
        prompt = f"""You are an expert academic assistant. Your task is to provide a comprehensive solution for the following university-level assignment.
Please analyze the assignment description and any supplementary content (files, transcripts) carefully and generate a complete response.
Only provide the answer to the question in a proper MLA essay format. Do not restate my question or offer a follow up question.

--- ASSIGNMENT DETAILS ---
Assignment Name: {assignment.name}
Description (cleaned):
{assignment.description}
--- END OF ASSIGNMENT DETAILS ---

--- SUPPLEMENTARY CONTENT (Files & Transcripts) ---
{all_supplementary_content}
--- END OF SUPPLEMENTARY CONTENT ---

Please provide your solution below:"""

        self._report_activity(f"Generated_prompt_length_{len(prompt)}_for_{assignment.name}")
        prompt_filename_base = re.sub(r'[^a-zA-Z0-9_]', '_', assignment.name[:50])
        prompt_filename = Path(f"full_prompt_{prompt_filename_base}.txt")
        try:
            async with aiofiles.open(prompt_filename, "w", encoding="utf-8") as f: await f.write(prompt)
            self._report_activity(f"Saved_prompt_to_{prompt_filename}")
        except Exception as e: self.logger.error(f"Error saving prompt: {e}") # Fallback not strictly needed if GUI handles downloads

        self._report_activity(f"Generating_solution_with_OpenAI_for_{assignment.name}")
        answer_content, answer_filename_str = "[Error generating solution]", ""
        try:
            response = await self.openai_client.chat.completions.create(
                model=self.settings.HW_MODEL_NAME,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that completes university homework concisely and accurately, adhering to specified formats like MLA."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
            )
            answer_content = response.choices[0].message.content or "[No content in AI response]"
            self._report_activity(f"Received_solution_from_OpenAI_length_{len(answer_content)}_for_{assignment.name}")
            answer_filename_base = re.sub(r'[^a-zA-Z0-9_]', '_', assignment.name[:50])
            answer_filename = Path(f"{answer_filename_base}_answer.md")
            async with aiofiles.open(answer_filename, "w", encoding="utf-8") as f: await f.write(answer_content)
            self._report_activity(f"Saved_answer_to_{answer_filename}")
            answer_filename_str = str(answer_filename)
        except Exception as e:
            self.logger.error(f"Failed to answer assignment {assignment.name}: {e}")
            self._report_activity(f"Failed_OpenAI_solution_{assignment.name}_{e}")
            answer_content = f"[Error generating solution via API: {e}]"
        
        return {
            "prompt_file": str(prompt_filename),
            "answer_file": answer_filename_str,
            "answer_content": answer_content,
            "assignment_details_text": f"{initial_details_text}\nGenerated prompt length: {len(prompt)}\nSupplementary content parts: {len(supplementary_content_parts)}"
        }

# Main CLI execution part (can be kept for testing or removed if GUI is primary)
async def main_cli():
    try:
        settings = Settings()
    except Exception as e:
        logging.error(f"Configuration error: {e}")
        return

    async with AssignmentSolver(settings) as solver: # No callback for CLI
        canvas_ok = await solver.test_canvas_connection()
        if not canvas_ok:
            solver.logger.error("Canvas connection failed. Exiting.")
            return

        assignments = await solver.fetch_all_assignments()
        if not assignments:
            solver.logger.warning("No assignments found. Exiting.")
            return

        while True:
            print("\n--- Available Assignments (CLI) ---")
            for i, assign in enumerate(assignments):
                print(f"  {i + 1}. {assign.name} ({len(assign.links)} links, {len(assign.youtube_video_ids)} YT)")
            print("  q. Quit")
            choice = input("\nEnter assignment number (or 'q' to quit): ")
            if choice.lower() == 'q': print("Exiting CLI."); break
            try:
                selected_assignment = assignments[int(choice) - 1]
                results = await solver.generate_solution(selected_assignment)
                print("\n--- SOLUTION ---")
                print(results["answer_content"])
                print(f"\nPrompt saved to: {results['prompt_file']}")
                print(f"Answer saved to: {results['answer_file']}")
            except (ValueError, IndexError): print("Invalid input.")
            except Exception as e: print(f"An error occurred: {e}")

if __name__ == "__main__":
    # asyncio.run(main_cli()) # Comment out if only running through GUI
    pass