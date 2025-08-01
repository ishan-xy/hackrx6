import os
import json
import re
from typing import List, Dict, Any
from dotenv import load_dotenv
import google.generativeai as genai

class GeneratorAgent:
    """
    Generates a final, structured JSON answer based on the retrieved document chunks.
    """
    _model = None
    _initialized = False

    def __init__(self):
        if not self._initialized:
            load_dotenv()
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY not found in environment variables.")
            genai.configure(api_key=api_key)
            GeneratorAgent._model = genai.GenerativeModel("gemini-2.0-flash-lite")
            GeneratorAgent._initialized = True

    @staticmethod
    def _extract_json(text: str) -> dict:
        """
        A more robust function to extract and clean a JSON object from a raw string.
        """
        # Remove markdown code block fences and leading/trailing whitespace
        text = re.sub(r"```json\n?|\n```", "", text.strip())
        
        # Find the JSON block using the first '{' and the last '}'
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if not json_match:
            print(f"⚠️ Failed to find JSON object in text:\n{text}")
            raise ValueError("No valid JSON object found in LLM response.")
            
        json_str = json_match.group(0)

        # **FIX 1: Remove invalid backslash escapes that are not part of a valid sequence**
        # This looks for a backslash that is NOT followed by ", \, /, b, f, n, r, t, or u.
        json_str = re.sub(r'\\(?!["\\/bfnrtu])', '', json_str)
        
        # Replace all newline characters with a space to ensure single-line validity for parsing.
        json_str = json_str.replace('\n', ' ')
        
        # **FIX 2: Remove trailing commas before closing braces or brackets**
        json_str = re.sub(r',\s*([\}\]])', r'\1', json_str)

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON parsing failed. Error: {e}")
            print(f"Raw string after cleaning was:\n{json_str}")
            raise

    def generate_answer(self, raw_query: str, retrieved_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generates a structured JSON response based on the query and retrieved context.
        """
        if not retrieved_chunks:
            return {
                "decision": "Not Found",
                "amount": None,
                "justification": "Could not find relevant information in the provided documents.",
                "clauses": []
            }

        # Create a clean, readable context from the retrieved chunks.
        context = ""
        for i, chunk in enumerate(retrieved_chunks):
            metadata = chunk.get("metadata", {})
            content = metadata.get("text_content", "N/A")
            document = metadata.get("document_name", "Unknown")
            section_path = " > ".join(metadata.get("section_hierarchy", ["General"]))
            
            context += f"--- Context Chunk {i+1} ---\n"
            context += f"Document: {document}\n"
            context += f"Section: {section_path}\n"
            context += f"Content: {content}\n\n"

        # The prompt is now more direct and emphasizes a single-line, valid JSON output.
        # prompt = f"""
        # You are an expert insurance analyst. Answer the user's query based ONLY on the provided context chunks.

        # **Instructions:**
        # 1.  Analyze the User Query.
        # 2.  Review the Context Chunks to find the most relevant information.
        # 3.  Synthesize a concise answer. Do not use outside knowledge.
        # 4.  You MUST respond with a single, strictly valid JSON object. No markdown, no newlines in strings, and no trailing commas.

        # **JSON Schema:**
        # {{
        #   "decision": "A direct summary of the answer.",
        #   "amount": null_or_number,
        #   "justification": "A detailed explanation, referencing information from the context.",
        #   "clauses": [{{ "content": "Exact clause text.", "document": "Source document name.", "section": "Full section path." }}]
        # }}

        # **Context Chunks:**
        # {context}

        # **User Query:** {raw_query}

        # **JSON Answer:**
        # """
        prompt = f"""
        You are an expert insurance analyst. Your task is to answer a user's query based ONLY on the provided context chunks from policy documents. You MUST respond with a single, strictly valid JSON object. No markdown, no newlines in strings, and no trailing commas.
        
        **JSON Schema:**
        {{"decision": "A direct summary of the answer.","amount": "The relevant monetary amount as a number, or null if not applicable.","justification": "A detailed explanation, referencing information from the context.","clauses": [{{"content": "Exact clause text.","document": "Source document name.","section": "Full section path."}}]}}
        
        ---
        **EXAMPLE 1**
        
        **Context Chunks:**
        --- Context Chunk 1 ---
        Document: National Parivar Mediclaim Plus Policy.md
        Section: 4 EXCLUSIONS > 4.1. Pre-Existing Diseases (Excl 01)
        Content: a) Expenses related to the treatment of a Pre-Existing Disease (PED) and its direct complications shall be excluded until the expiry of thirty six (36) months of continuous coverage after the date of inception of the first policy with us.
        
        **User Query:** What is the waiting period for pre-existing diseases (PED) to be covered?
        
        **JSON Answer:**
        {{"decision": "There is a waiting period of thirty-six (36) months of continuous coverage from the first policy inception for pre-existing diseases and their direct complications to be covered.","amount": null,"justification": "The policy explicitly states under Section 4.1 that expenses for Pre-Existing Diseases (PED) and their complications are excluded until a 36-month period of continuous coverage has passed.","clauses": [{{"content": "Expenses related to the treatment of a Pre-Existing Disease (PED) and its direct complications shall be excluded until the expiry of thirty six (36) months of continuous coverage after the date of inception of the first policy with us.","document": "National Parivar Mediclaim Plus Policy.md","section": "4 EXCLUSIONS > 4.1. Pre-Existing Diseases (Excl 01)"}}]}}
        
        ---
        **EXAMPLE 2**
        
        **Context Chunks:**
        --- Context Chunk 1 ---
        Document: National Parivar Mediclaim Plus Policy.md
        Section: 3 BENEFITS COVERED UNDER THE POLICY > 3.1.14 Maternity
        Content: The Company shall indemnify Maternity Expenses as described below for any female Insured Person, and also Pre-Natal and Post-Natal Hospitalisation expenses per delivery, including expenses for necessary vaccination for New Born Baby, subject to the limit as shown in the Table of Benefits. The female Insured Person should have been continuously covered for at least 24 months before availing this benefit.
        --- Context Chunk 2 ---
        Document: National Parivar Mediclaim Plus Policy.md
        Section: 4 EXCLUSIONS > 4.2.f.iii. Two years waiting period
        Content: Hysterectomy, Cataract...
        
        **User Query:** Does this policy cover maternity expenses, and what are the conditions?
        
        **JSON Answer:**
        {{"decision": "Yes, the policy covers maternity expenses, subject to conditions.","amount": null,"justification": "The policy covers maternity expenses including childbirth and pre/post-natal care. The primary condition for eligibility is that the female insured person must have been continuously covered under the policy for at least 24 months.","clauses": [{{"content": "The Company shall indemnify Maternity Expenses as described below for any female Insured Person... The female Insured Person should have been continuously covered for at least 24 months before availing this benefit.","document": "National Parivar Mediclaim Plus Policy.md","section": "3 BENEFITS COVERED UNDER THE POLICY > 3.1.14 Maternity"}}]}}
        
        ---
        **ACTUAL TASK**
        
        **Context Chunks:**
        {context}
        **User Query:** {raw_query}
        
        **JSON Answer:**
        """

        try:
            response = self._model.generate_content(
                prompt,
                generation_config={"temperature": 0.1, "max_output_tokens": 2048}
            )
            return self._extract_json(response.text)
        except Exception as e:
            print(f"Error during answer generation for query '{raw_query}': {e}")
            # This is your error from the log
            if "JSON parsing failed" in str(e):
                 # We already printed the raw string in _extract_json
                 pass
            return {
                "decision": "Error",
                "amount": None,
                "justification": f"Failed to generate a valid response: {e}",
                "clauses": []
            }

if __name__ == '__main__':
    # This is a conceptual test, as it requires retrieved_chunks
    print("GeneratorAgent is ready. Use generate_answer(raw_query, retrieved_chunks) to generate answers.")