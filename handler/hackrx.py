from fastapi import APIRouter, Header, status, HTTPException
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from dotenv import load_dotenv
from handler.run import process_questions_parallel
import requests
import os
import threading
import tempfile

load_dotenv()

file_lock = threading.Lock()

router = APIRouter(
    prefix=f"{os.getenv('ROOT_ENDPOINT')}",
    responses={404: {"description": "Not found"}}
)


class Upload(BaseModel):
    documents: str
    questions: List[str]


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
        return {"answers": answers}
    except requests.RequestException as e:
        print(f"[ERROR] File download failed: {e}")
        raise HTTPException(status_code=400, detail=f"Download failed: {e}")
    except Exception as e:
        print(f"[ERROR] Internal error: {e}")
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
                print(f"[DEBUG] Cleaned up temp file: {temp_file}")
            except Exception as e:
                print(f"[WARNING] Failed to remove temp file: {e}")

