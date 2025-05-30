import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from urllib.parse import urljoin, urlparse, parse_qs
from typing import Mapping
import aiofiles
import aiohttp
from bs4 import BeautifulSoup, Tag
from canvasapi import Canvas
from openai import AsyncOpenAI, APIConnectionError, RateLimitError
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings

from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable

# configs
class Settings(BaseSettings):
    OPENAI_API_KEY: str
    CANVAS_API_KEY: str
    CANVAS_API_URL: str
    COURSE_ID: str
    max_file_size: int = 50 * 1024 * 1024 # 50 MB default max file size
    download_timeout: int = 30 # 30 seconds default download timeout

    @field_validator('COURSE_ID')
    def validate_COURSE_ID(cls, v):
        # ensures course_id is a valid integer
        if not v or not v.isdigit():
            raise ValueError('Course ID must be a valid integer')
        return v

    class Config:
        env_file = ".env" 

# data structs
@dataclass
class AssignmentData:
    # holds structured data for a single assignment
    id: int
    name: str
    description: str
    links: List[str] = field(default_factory=list)
    youtube_video_ids: List[str] = field(default_factory=list)

def _extract_youtube_video_id(url: str) -> Optional[str]:
    # extracts youtube video id from various url formats using regex
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
        if match:
            if match.group(1):
                return match.group(1)
    return None

 # main class for fetching, processing, and preparing assignment data 
class AssignmentSolver:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = self._setup_logging()
        self.session: Optional[aiohttp.ClientSession] = None # for http requests
        self.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY) # openai api client
        self.canvas = Canvas(settings.CANVAS_API_URL, settings.CANVAS_API_KEY) # canvas api client
        self.downloads_dir = Path("downloads") # directory for temporary downloads
        self.downloads_dir.mkdir(exist_ok=True)
    
    # configures basic logging for the application
    def _setup_logging(self) -> logging.Logger:

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        return logging.getLogger(__name__)

 # initializes aiohttp session
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.settings.download_timeout)
        )
        return self


 # closes aiohttp session
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def test_canvas_connection(self) -> bool:
        try:
            user = self.canvas.get_current_user()
            self.logger.info(f"✅ Canvas connection successful. Logged in as: {user.name}")
            return True
        except Exception as e:
            self.logger.error(f"❌ Canvas connection failed: {e}")
            return False

    async def test_openai_connection(self) -> bool:
        try:
            await self.openai_client.models.list()
            self.logger.info("✅ OpenAI connection successful.")
            return True
        except (APIConnectionError, RateLimitError, Exception) as e:
            self.logger.error(f"❌ OpenAI connection failed: {e}")
            return False

    # pulls visible text, all general link hrefs, and youtube video ids from html content
    def _extract_links_yt_from_html(self, html_content: str, base_url_for_links: str) -> Tuple[str, List[str], List[str]]:
        if not html_content:
            return "", [], []
        
        soup = BeautifulSoup(html_content, "html.parser")
        cleaned_text = ""
        
        # remove unwanted tags like script, style, nav etc.
        for unwanted_tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'button', 'input']):
            unwanted_tag.decompose()

        # try to find main content area for better text extraction. this basically makes it so we dont get all the unnecessary
        # html stuff when we pull the info from page
        main_content_selectors = [
            'article.user_content', 'div.user_content',
            'div#content', 'main', 'div.content', 'div.assignment-description'
        ]
        main_area = None
        for selector in main_content_selectors:
            target_element = soup.select_one(selector) if ('.' in selector or '#' in selector) else soup.find(selector)
            if target_element:
                main_area = target_element
                break
        target_soup = main_area if main_area else soup # fallback to whole soup if no main area found

        # extract text from relevant tags within the target area or whole soup
        text_parts = []
        elements_for_text = main_area.find_all(True, recursive=False) if main_area else target_soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'pre', 'div', 'span', 'td', 'th'])
        if not elements_for_text and main_area is None : # ensure elements_for_text is populated even if main_area logic changes
            elements_for_text = target_soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'pre', 'div', 'span', 'td', 'th'])


        if elements_for_text:
            for element in elements_for_text:
                text = element.get_text(separator=' ', strip=True)
                if text:
                    text_parts.append(text)
            cleaned_text = "\n".join(text_parts)
        
        if not cleaned_text: # fallback to get_text on the entire target_soup if specific elements yield no text
            cleaned_text = target_soup.get_text(separator=' ', strip=True)


        general_links = []
        youtube_video_ids_found = set() 

        # find all 'a' tags with href attributes for links
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href')
            if href and isinstance(href, str):
                if href.startswith('#') or href.lower().startswith('javascript:'): # skip internal page links and javascript calls
                    continue
                
                video_id = _extract_youtube_video_id(href) # check if it's a youtube link
                if video_id:
                    youtube_video_ids_found.add(video_id)
                else: # otherwise, treat as a general link
                    try:
                        full_url = urljoin(base_url_for_links, href) # resolve relative links
                        general_links.append(full_url)
                    except Exception:
                        self.logger.warning(f"Could not form absolute URL for link: {href} with base {base_url_for_links}")

        # find all 'iframe' tags for embedded youtube videos
        for iframe_tag in soup.find_all('iframe', src=True):
            src = iframe_tag.get('src')
            if src and isinstance(src, str):
                video_id = _extract_youtube_video_id(src)
                if video_id:
                    youtube_video_ids_found.add(video_id)
        
        return cleaned_text, list(general_links), list(youtube_video_ids_found)
    
    # fetches all assignments for the configured course from canvas
    async def fetch_all_assignments(self) -> List[AssignmentData]:
    
        self.logger.info(f"Fetching assignments from course ID: {self.settings.COURSE_ID}...")
        try:
            course = self.canvas.get_course(self.settings.COURSE_ID)
            assignments_raw = list(course.get_assignments()) # get list of assignment objects
            
            structured_assignments = []
            for assign in assignments_raw:
                desc_html = getattr(assign, 'description', '') or '' # get assignment description html
                
                # extract text and links from the assignment's html description
                # canvas puts assignment file links in the description html, so we scrape them
                cleaned_desc_text, general_links, yt_ids = self._extract_links_yt_from_html(
                    desc_html,
                    self.settings.CANVAS_API_URL # base url for resolving relative links in canvas descriptions
                )
                
                structured_assignments.append(AssignmentData(
                    id=assign.id,
                    name=assign.name,
                    description=cleaned_desc_text,
                    links=general_links,
                    youtube_video_ids=yt_ids
                ))
            self.logger.info(f"Found {len(structured_assignments)} assignments.")
            return structured_assignments
        except Exception as e:
            self.logger.error(f"Failed to fetch assignments: {e}")
            return []
        
    # fetches transcript for a given youtube video id
    async def _get_youtube_transcript(self, video_id: str) -> Optional[str]:
        
        self.logger.info(f"Attempting to fetch transcript for YouTube video ID: {video_id}...")
        try:
            loop = asyncio.get_running_loop()
            # run synchronous library call in executor to avoid blocking asyncio loop
            transcript_list = await loop.run_in_executor(
                None,
                YouTubeTranscriptApi.get_transcript, video_id
            )
            transcript_text = " ".join([item['text'] for item in transcript_list])
            self.logger.info(f"Successfully fetched transcript for {video_id} (length: {len(transcript_text)}).")
            return transcript_text
        except TranscriptsDisabled:
            self.logger.warning(f"Transcripts are disabled for video ID: {video_id}.")
            return f"[Transcript disabled for YouTube video ID: {video_id}]"
        except NoTranscriptFound:
            self.logger.warning(f"No transcript found for video ID: {video_id} (it might be a music video, very short, or no speech).")
            return f"[No transcript available for YouTube video ID: {video_id}]"
        except VideoUnavailable:
            self.logger.warning(f"Video unavailable for video ID: {video_id}.")
            return f"[Video unavailable for YouTube video ID: {video_id}]"
        except Exception as e:
            self.logger.error(f"An unexpected error occurred fetching transcript for {video_id}: {str(e)}")
            return f"[Error fetching transcript for YouTube video ID: {video_id}. See logs for details.]"
            
    # downloads a file from a url to a temporary location
    async def _download_file(self, url: str) -> Optional[Path]:
        if _extract_youtube_video_id(url): # skip youtube urls, handled by transcript getter
            self.logger.info(f"Skipping file download for YouTube URL (transcript handled separately): {url}")
            return None
        
        try:
            if url.startswith(('data:', 'mailto:')): # skip non-downloadable url schemes
                self.logger.info(f"Skipping non-downloadable link: {url[:50]}...")
                return None

            async with self.session.get(url) as response: # perform http get request
                if response.status >= 400: # check for http errors
                    self.logger.error(f"Failed to download {url}: HTTP {response.status}")
                    return None
                
                content_type = response.headers.get('Content-Type', '').lower()
                content_disposition = response.headers.get('Content-Disposition')
                filename_from_header = None
                if content_disposition: # try to get filename from content-disposition header
                    match = re.search(r'filename="?([^"]+)"?', content_disposition)
                    if match:
                        filename_from_header = match.group(1)

                if filename_from_header: # sanitize filename from header
                    base_filename = re.sub(r'[^\w\-_\.]', '_', filename_from_header)
                else: # otherwise, derive filename from url path
                    parsed_url_path = Path(urlparse(url).path)
                    base_filename = re.sub(r'[^\w\-_\.]', '_', parsed_url_path.name if parsed_url_path.name else "downloaded_file")
                
                # ensure filename has an extension
                if not Path(base_filename).suffix and 'html' in content_type:
                    base_filename += ".html"
                elif not Path(base_filename).suffix: # default extension if none and not html
                        base_filename += ".dat"

                filepath = self.downloads_dir / f"{int(time.time())}_{base_filename}" # create unique filepath
                content_length = response.headers.get('Content-Length')
                # check if file size exceeds configured maximum
                if content_length and int(content_length) > self.settings.max_file_size:
                    self.logger.warning(f"File {url} is too large ({content_length} bytes). Skipping download.")
                    return None

                # write file content in chunks, checking size limit
                async with aiofiles.open(filepath, 'wb') as f:
                    downloaded_size = 0
                    async for chunk in response.content.iter_chunked(8192):
                        downloaded_size += len(chunk)
                        if downloaded_size > self.settings.max_file_size: # stop if max size exceeded during download
                            self.logger.warning(f"File {url} exceeded max size during download. Truncated.")
                            await f.close() 
                            os.remove(filepath) # remove partial file
                            return None
                        await f.write(chunk)
                
                self.logger.info(f"Downloaded: {filepath} (Type: {content_type})")
                return filepath
        except aiohttp.ClientError as e: # handle network errors
            self.logger.error(f"Network error downloading {url}: {e}")
            return None
        except Exception as e: # handle other download/save errors
            self.logger.error(f"Failed to download or save {url}: {e}")
            if 'filepath' in locals() and isinstance(filepath, Path) and filepath.exists():
                try: 
                    os.remove(filepath) # attempt to clean up partial file
                except OSError as oe:
                    self.logger.error(f"Could not remove partially downloaded file {filepath}: {oe}")
            return None

    # reads content of a downloaded file, processing based on extension
    async def _read_file_content(self, filepath: Path, original_url: str) -> str:
        file_extension = filepath.suffix.lower()
        file_name = filepath.name
        try:
            if filepath.stat().st_size == 0: # handle empty files
                return f"[Empty File: {file_name} from {original_url}]"

            if file_extension == '.html': # specific handling for html files
                try:
                    async with aiofiles.open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                        raw_html_content = await f.read()
                    if not raw_html_content.strip(): # check if html file is effectively empty
                        return f"[Empty HTML File: {file_name} from {original_url}]"
                    
                    self.logger.info(f"Extracting text from downloaded HTML file: {file_name} (from {original_url})")
                    # reuse html cleaning logic for downloaded html files
                    cleaned_text, _, _ = self._extract_links_yt_from_html(
                        raw_html_content,
                        original_url # use the file's own url as base for its internal links
                    )
                    if cleaned_text:
                        return cleaned_text
                    else: # fallback if no text extracted from html
                        return f"[No Text Content Extracted from HTML: {file_name} from {original_url}. It might be a non-textual page or require JavaScript.]"
                except Exception as e:
                    self.logger.error(f"Could not read or parse HTML file {file_name} from {original_url}: {e}")
                    return f"[Error processing HTML file {file_name} from {original_url}]"
            elif file_extension in ['.txt', '.md', '.py', '.js', '.json', '.xml', '.css', '.csv', '.rtf', '.c', '.cpp', '.java', '.log']:
                # read common text-based file types
                async with aiofiles.open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    content = await f.read()
                return content
            # placeholders for handling other file types (pdf, docx, etc.)
            elif file_extension == '.pdf':
                return f"[PDF File: {file_name} from {original_url} - PDF text extraction to be implemented (e.g., using PyPDF2 or pdfplumber).]"
            elif file_extension in ['.doc', '.docx']:
                return f"[Word Document: {file_name} from {original_url} - DOCX/DOC text extraction to be implemented (e.g., using python-docx).]"
            elif file_extension in ['.ppt', '.pptx']:
                return f"[PowerPoint Presentation: {file_name} from {original_url} - PPTX/PPT text extraction to be implemented (e.g., using python-pptx).]"
            elif file_extension == '.xlsx':
                return f"[Excel Spreadsheet: {file_name} from {original_url} - XLSX parsing to be implemented (e.g., using openpyxl to extract key data/sheets).]"
            elif file_extension in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.tiff', '.webp']:
                return f"[Image File: {file_name} from {original_url} - Visual content. Describe relevance if known from context.]"
            elif file_extension in ['.mp3', '.wav', '.aac', '.ogg', '.flac', '.m4a']:
                return f"[Audio File: {file_name} from {original_url} - Audio content. Transcribe or summarize if necessary and possible.]"
            elif file_extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv']:
                return f"[Video File (not YouTube): {file_name} from {original_url} - Media content. Consider summarization/transcription if needed.]"
            elif file_extension in ['.zip', '.tar', '.gz', '.rar', '.7z']:
                return f"[Archive File: {file_name} from {original_url} - Contains multiple files. Extraction not implemented.]"
            else: # fallback for unknown file types: try to read as text
                try:
                    async with aiofiles.open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                        content_sample = await f.read(2048) # read a sample
                        return f"[Potentially Textual Content from Unknown File Type ({file_name} from {original_url})]:\n{content_sample}{'... (content may be truncated)' if len(content_sample) == 2048 else ''}"
                except Exception: # if reading as text fails, mark as unsupported
                    return f"[Unsupported or Binary File Type: {file_name} from {original_url}]"
        except UnicodeDecodeError: # handle files that are binary or have wrong encoding
            return f"[Binary File (or wrong encoding): {file_name} from {original_url}]"
        except Exception as e: # general error reading file content
            self.logger.error(f"Could not read or process file content for {file_name} from {original_url}: {e}")
            return f"[Error reading file content: {file_name} from {original_url}]"

    # prepares all context for an assignment and formats it for openai prompt
    async def generate_solution(self, assignment: AssignmentData):
        self.logger.info(f"\nProcessing '{assignment.name}'...")
        
        supplementary_content_parts = [] # list to hold all extracted content
        
        # process general links found in assignment description
        if assignment.links:
            self.logger.info(f"Found {len(assignment.links)} general links for '{assignment.name}'. Attempting to download and process...")

            # helper function to process a single link (download and read content)
            async def process_one_link(url_to_process: str) -> Tuple[Optional[str], Optional[str], str]:
                # returns (filename, content, original_url)
                path_obj = await self._download_file(url_to_process) # download the file
                if path_obj:
                    content = await self._read_file_content(path_obj, url_to_process) # read its content
                    filename = path_obj.name
                    try:
                        path_obj.unlink() # delete temporary file
                        self.logger.debug(f"Temporary file {path_obj} deleted after processing.")
                    except OSError as e:
                        self.logger.warning(f"Could not delete temporary file {path_obj} (from link {url_to_process}): {e}")
                    return filename, content, url_to_process
                else: # if download failed or was skipped
                    return None, f"[Content from URL {url_to_process} was not downloaded or processed. See previous logs for reason (e.g. skipped, error, too large).]", url_to_process


            link_processing_tasks = [process_one_link(link) for link in assignment.links]
            link_processing_results = await asyncio.gather(*link_processing_tasks) # process all links concurrently

            for filename, content, original_url in link_processing_results:
                if content: # if any content or placeholder was generated
                    source_identifier = f"File: {filename} (from {original_url})" if filename else f"URL: {original_url}"
                    supplementary_content_parts.append(f"--- Content from {source_identifier} ---\n{content}\n--- End Content from {source_identifier} ---")
        
        # process youtube video links found in assignment description
        if assignment.youtube_video_ids:
            self.logger.info(f"Found {len(assignment.youtube_video_ids)} YouTube videos for '{assignment.name}'. Fetching transcripts...")
            transcript_fetch_tasks = [self._get_youtube_transcript(video_id) for video_id in assignment.youtube_video_ids]
            transcript_results = await asyncio.gather(*transcript_fetch_tasks) # fetch all transcripts concurrently
            
            for i, transcript_text_or_error_msg in enumerate(transcript_results):
                video_id = assignment.youtube_video_ids[i]
                supplementary_content_parts.append(f"--- YouTube Transcript (Video ID: {video_id}) ---\n{transcript_text_or_error_msg}\n--- End Transcript (Video ID: {video_id}) ---")
        
        # combine all supplementary content into a single string
        all_supplementary_content_str = "\n\n".join(supplementary_content_parts) if supplementary_content_parts else "[No downloadable files or YouTube transcripts processed.]"

        # construct the prompt for openai. IT NEEDS WORK
        prompt = f"""
You are an expert academic assistant. Your task is to provide a comprehensive solution for the following university-level assignment.

Please analyze the assignment description and any supplementary content (files, transcripts) carefully and generate a complete response.

--- ASSIGNMENT DETAILS ---
Assignment Name: {assignment.name}
Description (cleaned):
{assignment.description}
--- END OF ASSIGNMENT DETAILS ---
"""
        if supplementary_content_parts: # add supplementary content if available
            prompt += f"""
--- SUPPLEMENTARY CONTENT (Files & Transcripts) ---
{all_supplementary_content_str}
--- END OF SUPPLEMENTARY CONTENT ---
"""
        else:
            prompt += """
[No supplementary files or YouTube transcripts were attached or processed for this assignment.]
"""
        prompt += "\nPlease provide your solution below:"

        # log and display the prompt (or its beginning if too long)
        self.logger.info("This is the content that WOULD be sent to OpenAI:")
        print("\n" + "="*25 + " PROMPT CONTENT (for testing) " + "="*25)
        if len(prompt) > 7000: # if prompt is very long, save to file and show truncated version
            # create a sanitized filename for the prompt
            prompt_filename = f"full_prompt_{re.sub(r'[^a-zA-Z0-9_]', '_', assignment.name[:50])}.txt"
            try:
                with open(prompt_filename, "w", encoding="utf-8") as f:
                    f.write(prompt)
                self.logger.info(f"Full prompt has been written to {prompt_filename}")
            except Exception as e: # fallback filename if assignment name causes issues
                self.logger.error(f"Error writing full prompt to file: {e}")
                with open("full_prompt_output.txt", "w", encoding="utf-8") as f:
                    f.write(prompt)
                self.logger.info("Full prompt has been written to full_prompt_output.txt (fallback name)")

            print(prompt[:7000] + "\n\n... (prompt truncated for display in console, full prompt saved to file) ...\n")
        else:
            print(prompt)
        print("="*70 + "\n")
        # self.logger.info("Sending assignment to OpenAI for a solution. Please wait...")
        # try:
        #     response = await self.openai_client.chat.completions.create(
        #         model="gpt-4o",  # or any other model
        #         messages=[
        #             {"role": "system", "content": "You are a helpful academic assistant."},
        #             {"role": "user", "content": prompt}
        #         ],
        #         temperature=0.7,
        #     )
        #     solution = response.choices[0].message.content
        #     print("\n" + "="*25 + " GENERATED SOLUTION " + "="*25)
        #     print(solution)
        #     print("="*70 + "\n")

        # except Exception as e:
        #     self.logger.error(f"Could not get solution from OpenAI: {e}")


async def main():
    # main async function to run the assignment solver
    try:
        settings = Settings() # load application settings
    except Exception as e:
        logging.error(f"Configuration error: {e}. Make sure you have a .env file with all required keys.")
        return

    async with AssignmentSolver(settings) as solver: # use solver as an async context manager
        # test connections (canvas is essential)
        canvas_ok = await solver.test_canvas_connection()
        # openai_ok = await solver.test_openai_connection() # openai test currently commented out in original
        if not canvas_ok:
            solver.logger.error("Canvas service failed to connect. Please check API key/URL. Exiting.")
            return
        # solver.logger.info("OpenAI connection test skipped as API call is commented out.")


        assignments = await solver.fetch_all_assignments() # get all assignments
        if not assignments:
            solver.logger.warning("No assignments found or failed to fetch. Exiting.")
            return

        # interactive loop to let user choose an assignment to process
        while True:
            print("\n--- Available Assignments ---")
            for i, assign in enumerate(assignments):
                yt_count = len(assign.youtube_video_ids)
                file_count = len(assign.links)
                print(f"  {i + 1}. {assign.name} ({file_count} files, {yt_count} YouTube videos)")
            print("  q. Quit")
            
            choice = input("\nEnter the number of the assignment to process (or 'q' to quit): ")
            
            if choice.lower() == 'q': # quit option
                print("Exiting.")
                break
                
            try:
                choice_index = int(choice) - 1 # convert user input to 0-based index
                if 0 <= choice_index < len(assignments):
                    selected_assignment = assignments[choice_index]
                    await solver.generate_solution(selected_assignment) # process selected assignment
                else:
                    print("Invalid number. Please try again.")
            except ValueError: # handle non-integer input
                print("Invalid input. Please enter a number or 'q'.")

if __name__ == "__main__":
    # entry point of the script
    asyncio.run(main())