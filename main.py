from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import uuid
import aiofiles
import json

from task_engine import run_python_code
from gemini import parse_question_with_llm, answer_with_data

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ CRITICAL FIX: Use /tmp directory for Vercel
UPLOAD_DIR = "/tmp/uploads"

# ✅ REMOVE: Don't create directory at module level
# os.makedirs(UPLOAD_DIR, exist_ok=True)  # This causes 500 error

def ensure_upload_dir():
    """Create upload directory only when needed"""
    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR, exist_ok=True)
    return UPLOAD_DIR

@app.post("/api")
async def analyze(request: Request):
    # ✅ Create directory only when function is called
    base_upload_dir = ensure_upload_dir()
    
    # Create a unique folder for this request
    request_id = str(uuid.uuid4())
    request_folder = os.path.join(base_upload_dir, request_id)
    os.makedirs(request_folder, exist_ok=True)

    form = await request.form()
    question_text = None
    saved_files = {}

    # Save all uploaded files to the request folder
    for field_name, value in form.items():
        if hasattr(value, "filename") and value.filename:
            file_path = os.path.join(request_folder, value.filename)
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(await value.read())
            saved_files[field_name] = file_path

            if field_name == "questions.txt":
                async with aiofiles.open(file_path, "r") as f:
                    question_text = await f.read()
        else:
            saved_files[field_name] = value

    # Fallback: If no questions.txt, use the first file as question
    if question_text is None and saved_files:
        first_file = next(iter(saved_files.values()))
        if os.path.exists(first_file):
            async with aiofiles.open(first_file, "r") as f:
                question_text = await f.read()

    if not question_text:
        return JSONResponse({"message": "No question text provided"}, status_code=400)

    try:
        # Get code steps from LLM
        response = await parse_question_with_llm(
            question_text=question_text,
            uploaded_files=saved_files,
            folder=request_folder
        )

        # Execute generated code safely
        execution_result = await run_python_code(response["code"], response["libraries"], folder=request_folder)

        count = 0
        while execution_result["code"] == 0 and count < 3:
            print(f"Error occurred while scraping x{count}")
            new_question_text = str(question_text) + " previous time this error occurred " + str(execution_result["output"])
            response = await parse_question_with_llm(
                question_text=new_question_text,
                uploaded_files=saved_files,
                folder=request_folder
            )
            execution_result = await run_python_code(response["code"], response["libraries"], folder=request_folder)
            count += 1

        if execution_result["code"] == 1:
            execution_result = execution_result["output"]
        else:
            return JSONResponse({"message": "Error occurred while scraping.", "details": execution_result.get("output", "")})

        # Get answers from LLM
        gpt_ans = await answer_with_data(response["questions"], folder=request_folder)

        # Executing code
        try:
            final_result = await run_python_code(gpt_ans["code"], gpt_ans["libraries"], folder=request_folder)
        except Exception as e:
            gpt_ans = await answer_with_data(response["questions"] + str(" Please follow the json structure"), folder=request_folder)
            final_result = await run_python_code(gpt_ans["code"], gpt_ans["libraries"], folder=request_folder)

        count = 0
        json_str = 1
        while final_result["code"] == 0 and count < 3:
            print(f"Error occurred while executing code x{count}")
            new_question_text = str(response["questions"]) + " previous time this error occurred " + str(final_result["output"])
            if json_str == 0:
                new_question_text += " follow the structure {'code': '', 'libraries': ''}"
                
            gpt_ans = await answer_with_data(new_question_text, folder=request_folder)

            try:
                json_str = 0
                final_result = await run_python_code(gpt_ans["code"], gpt_ans["libraries"], folder=request_folder)
                json_str = 1
            except Exception as e:
                print(f"Exception occurred: {e}")
                count -= 1

            count += 1

        if final_result["code"] == 1:
            final_result = final_result["output"]
        else:
            result_path = os.path.join(request_folder, "result.json")
            if os.path.exists(result_path):
                with open(result_path, "r") as f:
                    data = json.load(f)
                return JSONResponse(content=data)
            else:
                return JSONResponse({"message": "Failed to generate results", "details": final_result.get("output", "")})

        result_path = os.path.join(request_folder, "result.json")
        if os.path.exists(result_path):
            with open(result_path, "r") as f:
                try:
                    data = json.load(f)
                    return JSONResponse(content=data)
                except Exception as e:
                    return JSONResponse({"message": f"Error occurred while processing result.json: {e}"})
        else:
            return JSONResponse({"message": "Processing completed", "result": final_result})

    except Exception as e:
        return JSONResponse({"message": f"API processing error: {str(e)}"}, status_code=500)

@app.get("/", response_class=HTMLResponse)
async def web_interface():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>🤖 Data Analyst Agent</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            /* Add your complete CSS styles here */
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 Data Analyst Agent</h1>
                <p>Intelligent Data Analysis & Visualization Platform</p>
            </div>
            
            <div class="content">
                <div class="example-box">
                    <h3>💡 Example Questions You Can Ask:</h3>
                    <ul class="example-list">
                        <li onclick="fillQuestion(this.textContent)">What are the top 10 highest-grossing movies worldwide?</li>
                        <li onclick="fillQuestion(this.textContent)">Show me a chart of Indian box office collections</li>
                        <li onclick="fillQuestion(this.textContent)">Compare movie ratings between different genres</li>
                        <li onclick="fillQuestion(this.textContent)">Analyze correlation between movie budget and revenue</li>
                        <li onclick="fillQuestion(this.textContent)">What are the trending topics on social media today?</li>
                        <li onclick="fillQuestion(this.textContent)">Create a visualization of stock market trends</li>
                    </ul>
                </div>
                
                <div class="form-section">
                    <form id="questionForm" onsubmit="submitQuestion(event)">
                        <label class="form-label">🎯 Ask Your Data Analysis Question:</label>
                        <textarea 
                            id="questionInput" 
                            name="question" 
                            class="question-input"
                            placeholder="Type your data analysis question here..."
                            required
                        ></textarea>
                        
                        <button type="submit" class="submit-btn">🔍 Analyze Data</button>
                        
                        <div class="loading" id="loading" style="display: none;">
                            <div class="spinner"></div>
                            <p>⏳ Processing your question...</p>
                        </div>
                    </form>
                </div>
                
                <div class="result-container" id="resultContainer" style="display: none;">
                    <h3>📊 Analysis Results</h3>
                    <div id="resultContent" class="result-content"></div>
                </div>
            </div>
        </div>
        
        <script>
            function fillQuestion(text) {
                document.getElementById('questionInput').value = text;
            }
            
            function submitQuestion(event) {
                event.preventDefault();
                // Add your JavaScript logic here
            }
        </script>
    </body>
    </html>
    """

@app.post("/web-api")
async def web_analyze(question: str = Form(...)):
    """Web interface endpoint for processing questions"""
    base_upload_dir = ensure_upload_dir()
    request_id = str(uuid.uuid4())
    request_folder = os.path.join(base_upload_dir, request_id)
    os.makedirs(request_folder, exist_ok=True)
    
    try:
        question_file = os.path.join(request_folder, "questions.txt")
        async with aiofiles.open(question_file, "w") as f:
            await f.write(question)
        
        saved_files = {"questions.txt": question_file}
        
        response = await parse_question_with_llm(
            question_text=question,
            uploaded_files=saved_files,
            folder=request_folder
        )
        
        execution_result = await run_python_code(response["code"], response["libraries"], folder=request_folder)
        
        if execution_result["code"] == 1:
            gpt_ans = await answer_with_data(response["questions"], folder=request_folder)
            final_result = await run_python_code(gpt_ans["code"], gpt_ans["libraries"], folder=request_folder)
            
            if final_result["code"] == 1:
                result_path = os.path.join(request_folder, "result.json")
                if os.path.exists(result_path):
                    with open(result_path, "r") as f:
                        data = json.load(f)
                    return {"question": question, "result": data, "status": "success"}
                else:
                    return {"question": question, "result": final_result["output"], "status": "success"}
            else:
                return {"question": question, "error": "Failed to generate final answer"}
        else:
            return {"question": question, "error": "Failed to process question"}
            
    except Exception as e:
        return {"question": question, "error": f"Processing error: {str(e)}"}

# ✅ ESSENTIAL: Add Vercel handler
# At the very end of your main.py file
from mangum import Mangum

# Simple, direct handler creation
handler = Mangum(app)

# For local development
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

