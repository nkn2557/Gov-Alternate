import httpx
from io import BytesIO
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from app.core.config import settings
import asyncio

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency at runtime
    PdfReader = None

class WebCrawler:
    def __init__(self):
        self.headers = {
            "User-Agent": "GovAlternateBatch/1.0 (+http://example.com)"
        }
        self.timeout = settings.CRAWLER_TIMEOUT_SECONDS
        self.client = httpx.AsyncClient(headers=self.headers, timeout=self.timeout, follow_redirects=True)

    async def close(self):
        await self.client.aclose()

    async def fetch_page(self, url: str) -> str:
        """
        Fetches the HTML content of a page.
        """
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            
            # Simple content cleaning
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Remove script and style elements
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()
                
            # Get text or simplified HTML
            # For Gemini, keeping semantic HTML tags is better than pure text
            return str(soup.body) if soup.body else str(soup)
            
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return ""

    def _extract_pdf_text(self, content: bytes) -> str:
        if PdfReader is None:
            print("PDF parsing skipped: pypdf is not installed.")
            return ""
        try:
            reader = PdfReader(BytesIO(content))
            texts = []
            for page in reader.pages:
                page_text = page.extract_text() or ""
                if page_text:
                    texts.append(page_text)
            return "\n".join(texts).strip()
        except Exception as e:
            print(f"Error parsing PDF content: {e}")
            return ""

    async def fetch_content(self, url: str, force_pdf: bool = False) -> tuple[str, bool]:
        """
        Fetches content and returns (text, is_pdf).
        """
        try:
            response = await self.client.get(url)
            response.raise_for_status()

            content_type = (response.headers.get("content-type") or "").lower()
            is_pdf_by_content = (
                content_type.startswith("application/pdf")
                or response.content[:4] == b"%PDF"
            )
            is_pdf = force_pdf or is_pdf_by_content

            if is_pdf:
                text = self._extract_pdf_text(response.content)
                if text:
                    return text, True
                if is_pdf_by_content:
                    return "", True

            soup = BeautifulSoup(response.text, "html.parser")
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()
            return (str(soup.body) if soup.body else str(soup)), False
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return "", False

    def extract_links(self, html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        links = set()
        for a in soup.find_all('a', href=True):
            href = a['href']
            full_url = urljoin(base_url, href)
            # Simple filter to keep within domain or specific logic
            if urlparse(full_url).netloc == urlparse(base_url).netloc:
                links.add(full_url)
        return list(links)
