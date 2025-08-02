from fastapi import APIRouter, Header, status, HTTPException
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from dotenv import load_dotenv
from handler.run import process_questions_parallel
import requests
import os
import threading
import tempfile
import json
import httpx

load_dotenv()

file_lock = threading.Lock()

router = APIRouter(
    prefix=f"{os.getenv('ROOT_ENDPOINT')}",
    responses={404: {"description": "Not found"}}
)

DISCORD_WEBHOOK_URL2 = os.getenv("DISCORD_WEBHOOK_URL2") or ""


class Upload(BaseModel):
    documents: str
    questions: List[str]


async def send_to_discord(webhook_url: str, content: str, embed_data: Optional[Dict[str, Any]] = None):
    """
    Sends a message to Discord webhook.
    
    Args:
        webhook_url (str): Discord webhook URL
        content (str): Message content (up to 2000 characters)
        embed_data (dict, optional): Embed data for rich formatting
    """
    if not webhook_url:
        print("[WARNING] Discord webhook URL not configured")
        return
    try:
        # Ensure content doesn't exceed Discord's 2000 character limit
        if len(content) > 2000:
            content = content[:1997] + "..."
        
        payload = {"content": content}
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                webhook_url,
                json=payload,
                timeout=10.0
            )
            response.raise_for_status()
            print("[DEBUG] Successfully sent message to Discord")
            
    except Exception as e:
        print(f"[ERROR] Failed to send Discord webhook: {e}")


async def send_hackrx_result_to_discord(questions: List[str], answers: List[str], document_url: str):
    """
    Sends HackRX processing results to Discord with formatted output.
    
    Args:
        questions (List[str]): List of questions processed
        answers (List[str]): List of corresponding answers
        document_url (str): URL of the processed document
    """
    try:
        # Create a formatted summary
        summary = f"**HackRX Processing Complete** 📋\n\n"
        summary += f"**Document:** {document_url}\n"
        summary += f"**Questions Processed:** {len(questions)}\n"
        summary += f"**Answers Generated:** {len(answers)}\n\n"
        
        # Add first few Q&A pairs as preview
        preview_count = min(3, len(questions))
        summary += "**Preview (First 3 Q&A pairs):**\n"
        
        for i in range(preview_count):
            question = questions[i][:100] + "..." if len(questions[i]) > 100 else questions[i]
            answer = answers[i][:150] + "..." if len(answers[i]) > 150 else answers[i]
            summary += f"\n**Q{i+1}:** {question}\n**A{i+1}:** {answer}\n"
        
        if len(questions) > preview_count:
            summary += f"\n... and {len(questions) - preview_count} more Q&A pairs"
        
        # Create an embed for better formatting
        embed_data = {
            "title": "HackRX Processing Results",
            "description": f"Successfully processed {len(questions)} questions from document",
            "color": 0x00ff00,  # Green color
            "fields": [
                {
                    "name": "Document URL",
                    "value": document_url,
                    "inline": False
                },
                {
                    "name": "Questions Count",
                    "value": str(len(questions)),
                    "inline": True
                },
                {
                    "name": "Answers Count", 
                    "value": str(len(answers)),
                    "inline": True
                }
            ],
            "timestamp": None  # Discord will use current timestamp
        }
        
        await send_to_discord(DISCORD_WEBHOOK_URL2, summary, embed_data)
        
    except Exception as e:
        print(f"[ERROR] Failed to send HackRX results to Discord: {e}")


def get_file_extension(response: requests.Response) -> str:
    content_type = response.headers.get('content-type', '').lower().split(';')[0]
    extension_map = {
        'application/pdf': '.pdf',
        'application/msword': '.doc',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
        'message/rfc822': '.eml',
        'application/vnd.ms-outlook': '.msg',
        'text/plain': '.txt'
    }
    return extension_map.get(content_type, '.pdf')


def download_file(url: str) -> str:
    """
    Downloads a file from the given URL and returns the local file path.
    """
    print(f"[DEBUG] Downloading file from URL: {url}")
    with requests.get(url, stream=True) as response:
        response.raise_for_status()
        extension = get_file_extension(response)
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as temp_f:
            for chunk in response.iter_content(chunk_size=8192):
                temp_f.write(chunk)
            print(f"[DEBUG] File downloaded at {temp_f.name}")
            return temp_f.name  # Return path to the downloaded file


def get_answers_from_file(file_path: str, questions: List[str]) -> List[str]:
    results = process_questions_parallel(questions)
    
    # Extract only the generated_answer from each result
    answers = []
    for result in results:
        if result.get("status") == "success":
            answers.append(result.get("generated_answer", ""))
        else:
            # For errors, include the error message as the answer
            answers.append(f"Error: {result.get('error', 'Unknown error')}")
    return answers


@router.post("/hackrx/run", status_code=status.HTTP_200_OK)
async def run_hackrx(req: Upload, Authorization: Optional[str] = Header(None)):
    print(f"[DEBUG] Received /hackrx/run request: documents={req.documents}, questions={req.questions}")
    temp_file = None
    try:
        temp_file = download_file(req.documents)
        answers = get_answers_from_file(temp_file, req.questions)
        print(f"[DEBUG] Answer extraction completed.")
        
        # Send results to Discord
        await send_hackrx_result_to_discord(req.questions, answers, req.documents)
        
        return {"answers": answers}
    except requests.RequestException as e:
        print(f"[ERROR] File download failed: {e}")
        # Send error to Discord
        await send_to_discord(DISCORD_WEBHOOK_URL2, f"**HackRX Error** ❌\n\nFile download failed: {e}\nDocument URL: {req.documents}")
        raise HTTPException(status_code=400, detail=f"Download failed: {e}")
    except Exception as e:
        print(f"[ERROR] Internal error: {e}")
        # Send error to Discord
        await send_to_discord(DISCORD_WEBHOOK_URL2, f"**HackRX Error** ❌\n\nInternal error: {e}\nDocument URL: {req.documents}")
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
                print(f"[DEBUG] Cleaned up temp file: {temp_file}")
            except Exception as e:
                print(f"[WARNING] Failed to remove temp file: {e}")