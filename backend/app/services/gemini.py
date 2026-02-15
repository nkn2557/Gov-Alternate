import os
import json
import re
from datetime import datetime, timezone
from google import genai
from google.cloud import firestore
from app.core.config import settings
from app.core.database import get_db


class APILimitExceededError(Exception):
    """Raised when daily API limit is exceeded."""
    pass


def get_gemini_api_key() -> str:
    """Returns the Gemini API key from environment variables."""
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")
    return api_key


def check_and_increment_api_usage() -> bool:
    """
    Checks if API usage is within daily limit and increments counter.
    Returns True if within limit, False if limit exceeded.
    """
    try:
        db = get_db()
        
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        doc_ref = db.collection(settings.API_COUNTER_COLLECTION).document(today)
        
        @firestore.transactional
        def update_counter(transaction, doc_ref):
            snapshot = doc_ref.get(transaction=transaction)
            
            if snapshot.exists:
                current_count = snapshot.get("count")
                if current_count >= settings.DAILY_API_LIMIT:
                    return False  # Limit exceeded
                
                transaction.update(doc_ref, {
                    "count": firestore.Increment(1),
                    "last_updated": firestore.SERVER_TIMESTAMP
                })
            else:
                transaction.set(doc_ref, {
                    "count": 1,
                    "date": today,
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "last_updated": firestore.SERVER_TIMESTAMP
                })
            
            return True
        
        transaction = db.transaction()
        return update_counter(transaction, doc_ref)
        
    except Exception as e:
        print(f"Error checking API usage: {e}")
        return False


def call_gemini_api(model: str, prompt: str) -> str:
    """
    Calls Gemini API with rate limiting check.
    Raises exception if daily limit is exceeded.
    """
    if not check_and_increment_api_usage():
        raise APILimitExceededError("Daily API call limit exceeded. Please try again tomorrow.")
    
    api_key = get_gemini_api_key()
    client = genai.Client(api_key=api_key)
    
    result = client.models.generate_content(
        model=model,
        contents=prompt,
    )
    
    return result.text


def parse_gemini_response(raw_response: str) -> dict:
    """
    Parses Gemini API response and extracts JSON data.
    Handles code blocks, trailing commas, and other common formatting issues.
    
    Args:
        raw_response: Raw text response from Gemini API
        
    Returns:
        Parsed JSON as dictionary, or empty dict if parsing fails
    """
    raw = raw_response.strip()
    print("Raw response:", raw)
    
    # Remove code blocks
    if raw.startswith("```"):
        raw = re.sub(r"^```json\s*", "", raw, flags=re.IGNORECASE | re.MULTILINE)
        raw = re.sub(r"^```", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"```$", "", raw, flags=re.MULTILINE).strip()
    
    # Find the start and end of JSON
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        print("Error: Could not find valid JSON in response")
        return {}
    
    candidate = raw[start:end + 1]
    
    # Parse JSON
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        # Remove trailing commas and retry
        candidate2 = re.sub(r",\s*}", "}", candidate)
        candidate2 = re.sub(r",\s*\]", "]", candidate2)
        try:
            return json.loads(candidate2)
        except json.JSONDecodeError:
            print("Failed to parse JSON even after cleanup")
            return {}