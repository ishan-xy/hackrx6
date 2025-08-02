from fastapi import APIRouter, Header, status, HTTPException
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel
from dotenv import load_dotenv
import shutil
import requests
import os
import json
import threading
import re
from urllib.parse import urlparse, unquote
import hashlib
import tempfile
import redis
import time

load_dotenv()

file_lock = threading.Lock()
r = redis.Redis(host='redis', port=6379, db=0, protocol=3)
CHANNEL_NAME = "hakrx_events"
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
    shutil.move(temp_filepath, final_filepath)
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
        r.publish(CHANNEL_NAME, json.dumps(event_data))
        print(f"Published {event_type} event to Redis")
    except Exception as e:
        print(f"Failed to publish event to Redis: {e}")


def wait_for_result(file_hash, timeout=30000):
    """
    Subscribe to 'file_results' channel, block until a result event
    for the given file_hash is received, or timeout in seconds.
    """
    pubsub = r.pubsub()
    pubsub.subscribe(CHANNEL_NAME)
    start_time = time.time()
    print(f"Waiting for 'result' event on file_hash {file_hash[:10]}...")
    for message in pubsub.listen():
        if message["type"] != "message":
            continue
        try:
            data = json.loads(message["data"])
            if data.get("event_type") == "result" and data.get("filehash") == file_hash:
                pubsub.close()
                print(f"Received result for file_hash {file_hash[:10]}")
                return data
        except Exception:
            pass
        if time.time() - start_time > timeout:
            pubsub.close()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timed out waiting for external file result."
            )

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
            if file_hash in metadata.get("files_by_hash", {}):
                print(f"Duplicate file detected (Hash: {file_hash[:10]}...).")
                existing_entry = metadata["files_by_hash"][file_hash]
                existing_filepath = os.path.join(downloads_dir, existing_entry["generic_filename"])

                cleanup_temp_file(temp_filepath)
                publish_file_event("run_hackrx", file_hash, existing_filepath)

                # ----- Wait for result event -----
                result_data = wait_for_result(file_hash, timeout=30)
                if result_data != None:
                    answers = result_data.get("answers", [])
                    return {"answers": answers}

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

        publish_file_event("run_hackrx", file_hash, final_filepath)

        # ----- Wait for result event -----
        result_data = wait_for_result(file_hash, timeout=30)
        if result_data is not None:
            answers = result_data.get("answers", [])
            print(f"Received {len(answers)} answers for file {file_hash[:10]}...")
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


# def wait_for_result2(timeout=30):
#     """
#     Subscribe to 'hackrx_events' channel, block until a result event
#     is received, or timeout in seconds.
#     """
#     pubsub = r.pubsub()
#     pubsub.subscribe(CHANNEL_NAME)
#     start_time = time.time()
#     print("Waiting for 'result' event...")
#     for message in pubsub.listen():
#         if message["type"] != "message":
#             continue
#         try:
#             data = json.loads(message["data"])
#             if data.get("event_type") == "result":
#                 pubsub.close()
#                 print("Received result event")
#                 return data
#         except Exception:
#             pass
#         if time.time() - start_time > timeout:
#             pubsub.close()
#             raise HTTPException(
#                 status_code=status.HTTP_504_GATEWAY_TIMEOUT,
#                 detail="Timed out waiting for result."
#             )
#         time.sleep(1)

# @router.post("/hackrx/run", status_code=status.HTTP_200_OK)
# def run_hackrx(req: Upload):
#     # print all questions
#     print("Received documents URL:", req.documents)
#     print(f"Received {len(req.questions)} questions.")
#     r.publish(CHANNEL_NAME, json.dumps({
#         "event_type": "run_hackrx",
#         "documents": req.documents,
#         "questions": req.questions
#     }))
#     # ----- Wait for result event -----
#     result_data = wait_for_result2(timeout=30)
#     if result_data is not None:
#         answers = result_data.get("answers", [])
#         return {"answers": answers}
    