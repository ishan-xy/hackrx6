from fastapi import APIRouter, Header, status, HTTPException
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel
from dotenv import load_dotenv
from ml_model.run import process_questions_parallel
import requests
import os
import json
import threading
import re
from urllib.parse import urlparse, unquote
import hashlib
import tempfile
import time

load_dotenv()

file_lock = threading.Lock()
router = APIRouter(
    prefix=f"{os.getenv('ROOT_ENDPOINT')}",
    responses={404: {"description": "Not found"}}
)

class Upload(BaseModel):
    documents: str
    questions: List[str]

def determine_file_extension(url: str, response: requests.Response) -> str:
    extension = ''
    # Method 1: Content-Disposition header
    try:
        content_disposition = response.headers.get('content-disposition', '')
        if content_disposition:
            filename_match = re.search(r'filename[^;=\n]*=(([\'"]).*?\2|[^;\n]*)', content_disposition)
            if filename_match:
                filename = filename_match.group(1).strip('"\'')
                _root, extension = os.path.splitext(filename)
                if extension:
                    print(f"Extension determined from Content-Disposition: {extension}")
                    return extension
    except Exception as e:
        print(f"Failed to extract extension from Content-Disposition: {e}")

    # Method 2: Content-Type header
    try:
        content_type = response.headers.get('content-type', '').lower().split(';')[0]
        extension_map = {
            'application/pdf': '.pdf',
            'text/plain': '.txt',
            'text/html': '.html',
            'application/msword': '.doc',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
            'application/vnd.ms-excel': '.xls',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
            'application/vnd.ms-powerpoint': '.ppt',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/svg+xml': '.svg',
            'application/json': '.json',
            'application/xml': '.xml',
            'text/xml': '.xml',
            'text/csv': '.csv',
            'application/zip': '.zip',
            'application/x-rar-compressed': '.rar',
            'application/x-7z-compressed': '.7z'
        }
        if content_type in extension_map:
            extension = extension_map[content_type]
            print(f"Extension determined from Content-Type: {extension}")
            return extension
    except Exception as e:
        print(f"Failed to extract extension from Content-Type: {e}")

    # Method 3: URL path
    try:
        parsed_url = urlparse(url)
        path = unquote(parsed_url.path)
        _root, extension = os.path.splitext(path)
        if extension:
            print(f"Extension determined from URL: {extension}")
            return extension
    except Exception as e:
        print(f"Failed to extract extension from URL: {e}")

    print("Could not determine file extension, will use default")
    return ''

def download_file_to_temp(url: str) -> Tuple[str, str, requests.Response]:
    temp_filepath = None
    try:
        hasher = hashlib.sha256()
        with tempfile.NamedTemporaryFile(delete=False) as temp_f:
            temp_filepath = temp_f.name
            with requests.get(url, stream=True) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=8192):
                    hasher.update(chunk)
                    temp_f.write(chunk)
        file_hash = hasher.hexdigest()
        return temp_filepath, file_hash, response
    except Exception as e:
        if temp_filepath and os.path.exists(temp_filepath):
            os.remove(temp_filepath)
        raise e

def get_or_create_metadata(downloads_dir: str) -> Dict[str, Any]:
    meta_path = os.path.join(downloads_dir, 'meta.json')
    try:
        with open(meta_path, 'r') as f:
            metadata = json.load(f)
        if "files_by_hash" not in metadata:
            print("Old meta.json format detected. Re-initializing.")
            metadata = {"files_by_hash": {}, "next_id": 1}
    except (FileNotFoundError, json.JSONDecodeError):
        metadata = {"files_by_hash": {}, "next_id": 1}
    return metadata

def save_metadata(downloads_dir: str, metadata: Dict[str, Any]) -> None:
    meta_path = os.path.join(downloads_dir, 'meta.json')
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=4)

def save_new_file(temp_filepath: str, downloads_dir: str, filename: str) -> str:
    final_filepath = os.path.join(downloads_dir, filename)
    os.rename(temp_filepath, final_filepath)
    return final_filepath

def cleanup_temp_file(temp_filepath: Optional[str]) -> None:
    if temp_filepath and os.path.exists(temp_filepath):
        try:
            os.remove(temp_filepath)
        except Exception as e:
            print(f"Failed to remove temp file {temp_filepath}: {e}")
def publish_file_event(event_type: str, file_hash: str, file_path: str) -> None:
    try:
        event_data = {
            "event_type": event_type,
            "filehash": file_hash,
            "filepath": file_path
        }
        print(f"Published {event_type} event to Redis")
    except Exception as e:
        print(f"Failed to publish event to Redis: {e}")

@router.post("/hackrx/run", status_code=status.HTTP_200_OK)
def run_hackrx(req: Upload, Authorization: Optional[str] = Header(None)):

    print("Received documents URL:", req.documents)
    print(f"Received {len(req.questions)} questions.")

    temp_filepath = None
    try:
        # Step 1: Download file and calculate hash
        temp_filepath, file_hash, response = download_file_to_temp(req.documents)

        # Step 2: Setup directories and load metadata (thread-safe)
        with file_lock:
            current_script_dir = os.path.dirname(os.path.abspath(__file__))
            downloads_dir = os.path.join(current_script_dir, '..', 'downloads')
            os.makedirs(downloads_dir, exist_ok=True)

            metadata = get_or_create_metadata(downloads_dir)

            # Step 3: Check for duplicates
            if file_hash not in metadata.get("files_by_hash", {}):
                # Step 4: Process new file
                extension = determine_file_extension(req.documents, response)
                next_id = metadata.get("next_id", 1)
                new_generic_filename = f"document{next_id}{extension or '.pdf'}"

                final_filepath = save_new_file(temp_filepath, downloads_dir, new_generic_filename)
                temp_filepath = None  # File has been moved, don't clean up

                # Update metadata
                metadata["files_by_hash"][file_hash] = {
                    "generic_filename": new_generic_filename
                }
                metadata["next_id"] = next_id + 1
                save_metadata(downloads_dir, metadata)
                print(f"New document saved at: {final_filepath}")

        # ----- Wait for result event -----
        results = process_questions_parallel(req.questions)
        answers = []
        for result in results:
            if result.get("status") == "success":
                answers.append(result.get("generated_answer", ""))
            else:
                # For errors, include the error message as the answer
                answers.append(f"Error: {result.get('error', 'Unknown error')}")

        return {"answers": answers}

    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Failed to download document. Error: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"An internal error occurred: {e}"
        )
    finally:
        cleanup_temp_file(temp_filepath)