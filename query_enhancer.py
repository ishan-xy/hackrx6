import os
import json
import re
from typing import List, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field
import google.generativeai as genai

# Pydantic model for structured, validated output
class EnhancedQuery(BaseModel):
    intent: str = Field(description="The primary user intent (e.g., 'coverage_check', 'waiting_period', 'definition').")
    entities: List[str] = Field(description="The main subjects of the query (e.g., ['knee surgery', 'maternity expenses']).")
    keywords: Optional[List[str]] = Field(default=None, description="Other important keywords (e.g., ['sub-limits', 'Plan A']).")
    conditions: Optional[List[str]] = Field(default=None, description="Specific conditions mentioned (e.g., ['pre-existing']).")
    raw_query: str = Field(description="The original user query.")

class QueryEnhancerAgent:
    """
    Enhances user queries into a structured format using Gemini with few-shot prompting.
    """
    _model = None
    _initialized = False

    def __init__(self):
        if not self._initialized:
            load_dotenv()
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY environment variable not set.")
            genai.configure(api_key=api_key)
            QueryEnhancerAgent._model = genai.GenerativeModel("gemini-2.0-flash-lite")
            QueryEnhancerAgent._initialized = True

    @staticmethod
    def _extract_json(text: str) -> dict:
        """
        Extracts and cleans a JSON object from a string, handling common LLM formatting issues.
        """
        # Find the JSON block using the first '{' and the last '}'
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in the response string.")
        
        json_str = json_match.group(0)
        
        # Remove trailing commas that cause parsing errors
        json_str = re.sub(r',\s*([\}\]])', r'\1', json_str)
        
        return json.loads(json_str)

    def enhance_query(self, query: str) -> EnhancedQuery:
        """
        Takes a raw user query and returns a structured Pydantic model.
        """
        # This detailed prompt with few-shot examples guides the LLM to produce the correct format.
        prompt = f"""
        You are an expert AI assistant for parsing insurance queries. Convert the user's query into a structured JSON object.
        Analyze to extract intent, entities, keywords, and conditions.
        Respond ONLY with a valid JSON object.

        **Schema:**
        {{
          "intent": "The user's goal (e.g., 'coverage_check', 'waiting_period', 'definition', 'exclusion_check').",
          "entities": ["Main subjects of the query."],
          "keywords": ["Other important terms."],
          "conditions": ["Specific conditions mentioned."],
          "raw_query": "The original user query."
        }}

        **Examples:**

        1. Query: "Does this policy cover knee surgery, and what are the conditions?"
           JSON: {{"intent": "coverage_check", "entities": ["knee surgery"], "keywords": null, "conditions": ["conditions"], "raw_query": "Does this policy cover knee surgery, and what are the conditions?"}}

        2. Query: "What is the waiting period for pre-existing diseases (PED) to be covered?"
           JSON: {{"intent": "waiting_period", "entities": ["pre-existing diseases"], "keywords": ["PED"], "conditions": null, "raw_query": "What is the waiting period for pre-existing diseases (PED) to be covered?"}}

        3. Query: "How does the policy define a 'Hospital'?"
           JSON: {{"intent": "definition", "entities": ["Hospital"], "keywords": null, "conditions": null, "raw_query": "How does the policy define a 'Hospital'?"}}

        4. Query: "Are there any sub-limits on room rent and ICU charges for Plan A?"
           JSON: {{"intent": "coverage_check", "entities": ["room rent", "ICU charges"], "keywords": ["sub-limits"], "conditions": ["Plan A"], "raw_query": "Are there any sub-limits on room rent and ICU charges for Plan A?"}}
        
        **User Query to Process:**
        Query: "{query}"
        JSON:
        """
        try:
            response = self._model.generate_content(
                prompt,
                generation_config={"temperature": 0.1, "max_output_tokens": 512}
            )
            response_data = self._extract_json(response.text)
            return EnhancedQuery(**response_data)

        except Exception as e:
            print(f"Error enhancing query '{query}': {e}. Falling back to basic structure.")
            return EnhancedQuery(
                intent="general_query",
                entities=[query],
                raw_query=query
            )

if __name__ == '__main__':
    agent = QueryEnhancerAgent()
    test_query = "Are the medical expenses for an organ donor covered under this policy?"
    enhanced = agent.enhance_query(test_query)
    print(enhanced.model_dump_json(indent=2))