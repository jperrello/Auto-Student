import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from urllib.parse import urljoin, urlparse
from typing import Mapping
import aiofiles
import aiohttp
from bs4 import BeautifulSoup, Tag
from canvasapi import Canvas
from openai import AsyncOpenAI, APIConnectionError, RateLimitError
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings

# configs
class Settings(BaseSettings):
    OPENAI_API_KEY: str
    CANVAS_API_KEY: str
    CANVAS_API_URL: str
    COURSE_ID: str
    max_file_size: int = 50 * 1024 * 1024  # 50MB
    download_timeout: int = 30

    @field_validator('COURSE_ID')
    def validate_COURSE_ID(cls, v):
        if not v or not v.isdigit():
            raise ValueError('Course ID must be a valid integer')
        return v

    class Config:
        env_file = ".env"

# data structs
@dataclass
class AssignmentData:
    id: int
    name: str
    description: str
    links: List[str] = field(default_factory=list)

# magic happens here
class AssignmentSolver:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = self._setup_logging()
        self.session: Optional[aiohttp.ClientSession] = None
        self.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.canvas = Canvas(settings.CANVAS_API_URL, settings.CANVAS_API_KEY)
        self.downloads_dir = Path("downloads")
        self.downloads_dir.mkdir(exist_ok=True)

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

    # connect to api
    async def test_canvas_connection(self) -> bool:
        """Tests the connection to the Canvas API."""
        try:
            user = self.canvas.get_current_user()
            self.logger.info(f"✅ Canvas connection successful. Logged in as: {user.name}")
            return True
        except Exception as e:
            self.logger.error(f"❌ Canvas connection failed: {e}")
            return False

    async def test_openai_connection(self) -> bool:
        """Tests the connection to the OpenAI API."""
        try:
            await self.openai_client.models.list()
            self.logger.info("✅ OpenAI connection successful.")
            return True
        except (APIConnectionError, RateLimitError, Exception) as e:
            self.logger.error(f"❌ OpenAI connection failed: {e}")
        
            return False

    # pulls visible text and all the link hrefs from the html
    # canvas puts assignment file links in the description html, so we scrape them
    def _extract_text_and_links(self, html: str) -> Tuple[str, List[str]]:
        """Extracts clean text and absolute links from HTML."""
        if not html:
            return "", []
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=' ', strip=True)
        links = [
            urljoin(self.settings.CANVAS_API_URL, str(a.get('href')))
            for a in soup.find_all('a', href=True)
            if isinstance(a, Tag) and a.get('href')
        ]
        return text, links

    async def fetch_all_assignments(self) -> List[AssignmentData]:
        """Fetches all assignments from the course and structures them."""
        self.logger.info(f"Fetching assignments from course ID: {self.settings.COURSE_ID}...")
        try:
            course = self.canvas.get_course(self.settings.COURSE_ID)
            assignments = list(course.get_assignments())
            
            structured_assignments = []
            for assign in assignments:
                desc_html = getattr(assign, 'description', '') or ''
                text_desc, links = self._extract_text_and_links(desc_html)
                structured_assignments.append(AssignmentData(
                    id=assign.id,
                    name=assign.name,
                    description=text_desc,
                    links=links
                ))
            self.logger.info(f"Found {len(structured_assignments)} assignments.")
            return structured_assignments
        except Exception as e:
            self.logger.error(f"Failed to fetch assignments: {e}")
            return []
            
    async def _download_file(self, url: str) -> Optional[Path]:
        """Downloads a single file and returns its local path."""
        try:
            async with self.session.get(url) as response:
                response.raise_for_status()
                # Generate a safe filename
                filename = re.sub(r'[^\w\-_\.]', '_', Path(urlparse(url).path).name)
                filepath = self.downloads_dir / f"{int(time.time())}_{filename}"
                
                async with aiofiles.open(filepath, 'wb') as f:
                    await f.write(await response.read())
                self.logger.info(f"Downloaded: {filepath}")
                return filepath
        except Exception as e:
            self.logger.error(f"Failed to download {url}: {e}")
            return None

    async def _read_file_content(self, filepath: Path) -> str:
        """Reads the content of a file, with a fallback for non-text files."""
        try:
            async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
                return await f.read()
        except UnicodeDecodeError:
            return f"[Content of non-text file: {filepath.name}]"
        except Exception as e:
            self.logger.error(f"Could not read file {filepath}: {e}")
            return f"[Error reading file: {filepath.name}]"


    async def generate_solution(self, assignment: AssignmentData):
        """Prepares the prompt and gets a solution from the LLM."""
        self.logger.info(f"\nProcessing '{assignment.name}'...")
        
        # 1. Download and read files
        file_contents = []
        download_tasks = [self._download_file(link) for link in assignment.links]
        downloaded_paths = await asyncio.gather(*download_tasks)

        for path in downloaded_paths:
            if path:
                content = await self._read_file_content(path)
                file_contents.append(f"--- Start of File: {path.name} ---\n{content}\n--- End of File: {path.name} ---")
                path.unlink() # Clean up file after reading

        all_file_content = "\n\n".join(file_contents)

        # 2. Construct the prompt WE NEED TO DO THIS !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        prompt = f"""
You are an expert academic assistant. Your task is to provide a comprehensive solution for the following university-level assignment.

Please analyze the assignment description and any attached file content carefully and generate a complete response.

--- ASSIGNMENT DETAILS ---
Assignment Name: {assignment.name}
Description:
{assignment.description}
--- END OF ASSIGNMENT DETAILS ---
"""
        if all_file_content:
            prompt += f"""
--- ATTACHED FILE CONTENT ---
{all_file_content}
--- END OF ATTACHED FILE CONTENT ---
"""
        prompt += "\nPlease provide your solution below:"

        # 3. Call OpenAI API
        self.logger.info("Sending assignment to OpenAI for a solution. Please wait...")
        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",  # or any other model
                messages=[
                    {"role": "system", "content": "You are a helpful academic assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
            )
            solution = response.choices[0].message.content
            print("\n" + "="*25 + " GENERATED SOLUTION " + "="*25)
            print(solution)
            print("="*70 + "\n")

        except Exception as e:
            self.logger.error(f"Could not get solution from OpenAI: {e}")


async def main():
    """Main entry point for the application."""
    try:
        settings = Settings()
    except Exception as e:
        logging.error(f"Configuration error: {e}. Make sure you have a .env file with all required keys.")
        return

    async with AssignmentSolver(settings) as solver:
        # --- 1. Test Connections ---
        canvas_ok = await solver.test_canvas_connection()
        openai_ok = await solver.test_openai_connection()

        if not (canvas_ok and openai_ok):
            solver.logger.error("One or more services failed to connect. Please check your API keys and URLs. Exiting.")
            return

        # --- 2. Fetch Assignments ---
        assignments = await solver.fetch_all_assignments()
        if not assignments:
            solver.logger.warning("No assignments found or failed to fetch. Exiting.")
            return

        # --- 3. Interactive Loop ---
        while True:
            print("\n--- Available Assignments ---")
            for i, assign in enumerate(assignments):
                print(f"  {i + 1}. {assign.name}")
            print("  q. Quit")
            
            choice = input("\nEnter the number of the assignment to process (or 'q' to quit): ")
            
            if choice.lower() == 'q':
                print("Exiting.")
                break
                
            try:
                choice_index = int(choice) - 1
                if 0 <= choice_index < len(assignments):
                    selected_assignment = assignments[choice_index]
                    await solver.generate_solution(selected_assignment)
                else:
                    print("Invalid number. Please try again.")
            except ValueError:
                print("Invalid input. Please enter a number or 'q'.")

if __name__ == "__main__":
    asyncio.run(main())