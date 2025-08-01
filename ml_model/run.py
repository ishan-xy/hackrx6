from query_enhancer import QueryEnhancerAgent
from retriever import RetrieverAgent
from generator import GeneratorAgent
from typing import Dict, Any, List
import redis, json
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time

enhancer = QueryEnhancerAgent()
retriever = RetrieverAgent()
generator = GeneratorAgent()

def extract_decision_from_answer(answer: Dict[str, Any]) -> str:
    """Extract the main decision/answer from the generated response"""
    if isinstance(answer, dict):
        # Try to get the main content from different possible keys
        for key in ['decision', 'answer', 'response', 'content', 'text']:
            if key in answer and answer[key]:
                return str(answer[key])
        # If no specific key found, convert the whole dict to string
        return str(answer)
    return str(answer)

def process_single_question(user_query):
    """Process a single question through the pipeline"""
    # Re-import agents inside the process to avoid multiprocessing issues
    from query_enhancer import QueryEnhancerAgent
    from retriever import RetrieverAgent
    from generator import GeneratorAgent

    enhancer = QueryEnhancerAgent()
    retriever = RetrieverAgent()
    generator = GeneratorAgent()

    try:
        enhanced = enhancer.enhance_query(user_query)
        chunks = retriever.retrieve_and_rerank(enhanced)
        answer = generator.generate_answer(user_query, chunks)
        generated_answer = extract_decision_from_answer(answer)

        return {
            "question": user_query,
            "enhanced": enhanced.model_dump() if hasattr(enhanced, 'model_dump') else str(enhanced),
            "chunks": chunks,
            "answer": answer,
            "generated_answer": generated_answer,
            "status": "success"
        }
    except Exception as e:
        return {
            "question": user_query,
            "error": str(e),
            "status": "error"
        }

def process_questions_parallel(questions: List[str], max_workers: int = 5) -> List[Dict[str, Any]]:
    """Process multiple questions in parallel using ThreadPoolExecutor"""
    if not questions:
        return []
    
    results = []
    
    # Use ThreadPoolExecutor for parallel processing
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all questions for processing
        future_to_question = {
            executor.submit(process_single_question, question): question 
            for question in questions
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_question):
            question = future_to_question[future]
            try:
                result = future.result(timeout=30)  # 30 second timeout per question
                results.append(result)
            except Exception as e:
                # Handle any exceptions that occurred during processing
                error_result = {
                    "question": question,
                    "error": f"Processing failed: {str(e)}",
                    "status": "error"
                }
                results.append(error_result)
    
    # Sort results to maintain original question order
    question_to_index = {q: i for i, q in enumerate(questions)}
    results.sort(key=lambda x: question_to_index.get(x.get("question", ""), len(questions)))
    
    return results

# def main():
#     """Main function to listen for Redis events and process questions"""
#     r = redis.Redis(host='localhost', port=6379, db=0, protocol=3)
#     pubsub = r.pubsub()
#     pubsub.subscribe(CHANNEL_NAME)
#     print("Listening for events on 'hackrx_events'...")
    
#     try:
#         for msg in pubsub.listen():
#             if msg["type"] == "message":
#                 try:
#                     data = json.loads(msg["data"])
#                 except Exception:
#                     data = msg["data"]

#                 # Only respond to run_hackrx to simulate worker logic
#                 if isinstance(data, dict) and data.get("event_type") == "run_hackrx":
#                     filehash = data.get("filehash")
#                     questions = data.get("questions", [])
                    
#                     print(f"Processing {len(questions)} questions for filehash: {filehash}")
#                     start_time = time.time()
                    
#                     # Process questions in parallel
#                     results = process_questions_parallel(questions)
                    
#                     # Extract only the generated_answer from each result
#                     answers = []
#                     for result in results:
#                         if result.get("status") == "success":
#                             answers.append(result.get("generated_answer", ""))
#                         else:
#                             # For errors, include the error message as the answer
#                             answers.append(f"Error: {result.get('error', 'Unknown error')}")
                    
#                     processing_time = time.time() - start_time
#                     print(f"Processed {len(questions)} questions in {processing_time:.2f} seconds")
                    
#                     # Publish result event
#                     result_event = {
#                         "event_type": "result",
#                         "filehash": filehash,
#                         "questions": questions,
#                         "answers": answers,
#                         "processing_time": processing_time,
#                         "status": "result_ready"
#                     }
#                     r.publish(CHANNEL_NAME, json.dumps(result_event))
#                     print(f"Published results for filehash: {filehash}")

#     except KeyboardInterrupt:
#         print("Stopped listening.")
#     finally:
#         pubsub.close()

# if __name__ == "__main__":
#     main()