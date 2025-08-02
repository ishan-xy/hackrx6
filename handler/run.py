from handler.query_enhancer import QueryEnhancerAgent
from handler.retriever import RetrieverAgent
from handler.generator import GeneratorAgent
from typing import Dict, Any, List
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time

enhancer = QueryEnhancerAgent()
retriever = RetrieverAgent()
generator = GeneratorAgent()
CHANNEL_NAME = "hakrx_events"


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
    from handler.query_enhancer import QueryEnhancerAgent
    from handler.retriever import RetrieverAgent
    from handler.generator import GeneratorAgent
    print(f"Processing question: {user_query}")
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

def process_questions_parallel(questions: List[str], max_workers: int = 10) -> List[Dict[str, Any]]:
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