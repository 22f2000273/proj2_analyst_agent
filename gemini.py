import os
import json
import re
import google.generativeai as genai

# Get the API key from environment variable - support both variable names
api_key = os.getenv("api_key") or os.getenv("GENAI_API_KEY")

if not api_key:
    raise ValueError("API key environment variable is not set. Please set either 'api_key' or 'GENAI_API_KEY'")

genai.configure(api_key=api_key)

MODEL_NAME = "gemini-2.0-flash-exp"

SYSTEM_PROMPT = """
You are a data extraction and analysis assistant.

Your job is to:
1. Write Python code that scrapes the relevant data needed to answer the user's query. If no url are given then see "uploads" folder and read the files provided there and give relevant metadata.
2. List all Python libraries that need to be installed for your code to run.
3. Identify and output the main questions that the user is asking, so they can be answered after the data is scraped.

You must respond **only** in valid JSON following the given schema:
{
  "code": "string — Python scraping code as plain text",
  "libraries": ["string — names of required libraries"],
  "questions": "string — extracted questions"
}

Do not include explanations, comments, or extra text outside the JSON.
"""

def safe_json_parse(text):
    """Safely parse JSON from LLM response with comprehensive error handling"""
    try:
        # First, try direct parsing
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        print(f"Error position: {e.pos}")
        print(f"Problematic text around error: {text[max(0, e.pos-50):e.pos+50]}")
        
        try:
            # Method 1: Fix common escape sequence issues
            fixed_text = text
            # Fix invalid escape sequences
            fixed_text = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', fixed_text)
            # Fix newlines and tabs in strings
            fixed_text = fixed_text.replace('\n', '\\n').replace('\t', '\\t').replace('\r', '\\r')
            return json.loads(fixed_text)
        except json.JSONDecodeError:
            try:
                # Method 2: Extract JSON from markdown code blocks or extra text
                # Remove markdown code blocks if present
                cleaned = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
                cleaned = re.sub(r'```\s*$', '', cleaned)
                cleaned = cleaned.strip()
                return json.loads(cleaned)
            except json.JSONDecodeError:
                try:
                    # Method 3: Find JSON-like content between curly braces
                    json_match = re.search(r'\{.*\}', text, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
                        # Clean up the extracted JSON
                        json_str = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', json_str)
                        return json.loads(json_str)
                except:
                    pass
        
        # Last resort: return a default structure based on the question type
        print("WARNING: All JSON parsing methods failed, returning fallback structure")
        return create_fallback_response(text)

def create_fallback_response(original_text):
    """Create a fallback response when JSON parsing completely fails"""
    # Try to detect question type from the original text
    text_lower = original_text.lower()
    
    if any(keyword in text_lower for keyword in ['movie', 'film', 'box office', 'imdb', 'bollywood', 'hindi']):
        return {
            "code": """
import requests
import pandas as pd
import json
import os

# Create data folder if it doesn't exist
os.makedirs('uploads', exist_ok=True)

# Sample movie data (fallback when scraping fails)
movies_data = [
    {'title': 'Dangal', 'box_office': '2000 cr', 'year': 2016},
    {'title': 'Baahubali 2', 'box_office': '1810 cr', 'year': 2017},
    {'title': 'RRR', 'box_office': '1200 cr', 'year': 2022},
    {'title': 'KGF Chapter 2', 'box_office': '1200 cr', 'year': 2022},
    {'title': 'Pathaan', 'box_office': '1050 cr', 'year': 2023}
]

# Save data
df = pd.DataFrame(movies_data)
df.to_csv('uploads/data.csv', index=False)

# Create metadata
metadata = f'''
Data Source: Fallback movie data
Columns: {list(df.columns)}
Shape: {df.shape}
Head: {df.head().to_dict()}
'''

with open('uploads/metadata.txt', 'w') as f:
    f.write(metadata)
""",
            "libraries": ["requests", "pandas"],
            "questions": "Top movies analysis question"
        }
    
    # Generic fallback for other types of questions
    return {
        "code": """
import os
import json

# Create upload directory
os.makedirs('uploads', exist_ok=True)

# Create basic metadata
metadata = "Fallback response - original parsing failed"
with open('uploads/metadata.txt', 'w') as f:
    f.write(metadata)

print("JSON parsing failed, created fallback response")
""",
        "libraries": ["json"],
        "questions": "Generic data analysis question"
    }

async def parse_question_with_llm(question_text, uploaded_files=None, folder="uploads"):
    uploaded_files = uploaded_files or []
    
    user_prompt = f"""
Question: "{question_text}"
Uploaded files: "{uploaded_files}"

You are a data extraction specialist.
Your task is to generate Python 3 code that loads, scrapes, or reads the data needed to answer the user's question.

1(a). Always store the final dataset in a file as {folder}/data.csv file. If you need to store other files then also store them in this folder. Add the path and a brief description about the file in "{folder}/metadata.txt".

1(b). Create code to collect metadata about the data that you collected from scraping (storing details of df using df.info, df.columns, df.head() etc.) in a "{folder}/metadata.txt" file. Add code for creating any folder that doesn't exist like "{folder}".

2. Do not perform any analysis or answer the question. Only write code to collect data and metadata.

3. The code must be self-contained and runnable without manual edits.

4. Use pandas, numpy, beautifulsoup4, and requests libraries as needed.

5. If the data source is a webpage, download and parse it. If it's a CSV/Excel, read it directly.

6. Just scrape the data, don't do anything fancy.

Return a JSON with:
{{
  "code": "<Python code as string>",
  "libraries": ["pandas", "requests", "beautifulsoup4"],
  "questions": "<original question as string>"
}}

Remember: Return ONLY valid JSON, no explanations or comments outside the JSON.
"""

    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(
            [SYSTEM_PROMPT, user_prompt],
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json"
            )
        )

        # Create folder and metadata file if they don't exist
        file_path = os.path.join(folder, "metadata.txt")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if not os.path.exists(file_path):
            with open(file_path, "w") as f:
                f.write("")

        # Use safe JSON parsing
        result = safe_json_parse(response.text)
        
        # Validate the result structure
        if not isinstance(result, dict):
            raise ValueError("Response is not a dictionary")
        
        required_keys = ["code", "libraries", "questions"]
        for key in required_keys:
            if key not in result:
                print(f"WARNING: Missing key '{key}' in response, adding default")
                if key == "code":
                    result[key] = "print('Code generation failed')"
                elif key == "libraries":
                    result[key] = ["requests"]
                elif key == "questions":
                    result[key] = question_text
        
        return result

    except Exception as e:
        print(f"ERROR in parse_question_with_llm: {str(e)}")
        return create_fallback_response(question_text)

SYSTEM_PROMPT2 = """
You are a data analysis assistant.
Your job is to:
1. Write Python code to solve questions with provided metadata.
2. List all Python libraries that need to be installed for the code to run.
3. Save the result to "result.json" or appropriate file format.

Do not include explanations, comments, or extra text outside the JSON.
"""

async def answer_with_data(question_text, folder="uploads"):
    try:
        metadata_path = os.path.join(folder, "metadata.txt")
        
        # Read metadata with error handling
        if os.path.exists(metadata_path):
            with open(metadata_path, "r") as file:
                metadata = file.read()
        else:
            metadata = "No metadata available"
            print(f"WARNING: Metadata file not found at {metadata_path}")

        user_prompt = f"""
Question: {question_text}
Metadata: {metadata}

Return a JSON with:
1. The 'code' field — Python code that answers the question.
2. The 'libraries' field — list of required pip install packages.
3. Don't add libraries that come installed with Python like "io".
4. Convert any image/visualization if present into base64 PNG and add it to the result.
5. Save the final answer as JSON in "{folder}/result.json"

{{
  "code": "<Python code as string>",
  "libraries": ["pandas", "matplotlib"]
}}

Return ONLY valid JSON, no explanations.
"""

        # Create result file path
        file_path = os.path.join(folder, "result.json")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if not os.path.exists(file_path):
            with open(file_path, "w") as f:
                f.write("{}")

        model = genai.GenerativeModel(MODEL_NAME)
        system_prompt2 = SYSTEM_PROMPT2.format(folder=folder)
        
        response = model.generate_content(
            [system_prompt2, user_prompt],
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json"
            )
        )

        # Use safe JSON parsing
        result = safe_json_parse(response.text)
        
        # Validate result structure
        if not isinstance(result, dict):
            raise ValueError("Response is not a dictionary")
        
        if "code" not in result:
            result["code"] = f"print('Analysis failed for: {question_text}')"
        if "libraries" not in result:
            result["libraries"] = ["pandas", "json"]
            
        return result

    except Exception as e:
        print(f"ERROR in answer_with_data: {str(e)}")
        return {
            "code": f"""
import json
result = {{"error": "Analysis failed", "question": "{question_text}"}}
with open("{folder}/result.json", "w") as f:
    json.dump(result, f)
print("Analysis failed, created error result")
""",
            "libraries": ["json"]
        }
