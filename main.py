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

# ✅ CRITICAL FIX 1: Use /tmp directory for Vercel
UPLOAD_DIR = "/tmp/uploads"

# ✅ CRITICAL FIX 2: REMOVE this line completely - it causes the filesystem error
# os.makedirs(UPLOAD_DIR, exist_ok=True)  # ❌ DELETE THIS LINE

def ensure_upload_dir():
    """Create upload directory only when needed"""
    try:
        if not os.path.exists(UPLOAD_DIR):
            os.makedirs(UPLOAD_DIR, exist_ok=True)
        return UPLOAD_DIR
    except Exception as e:
        print(f"Warning: Could not create upload directory: {e}")
        return "/tmp"

@app.post("/api")
async def analyze(request: Request):
    # Create directory only when function is called
    base_upload_dir = ensure_upload_dir()
    request_id = str(uuid.uuid4())
    request_folder = os.path.join(base_upload_dir, request_id)
    
    try:
        os.makedirs(request_folder, exist_ok=True)
    except Exception as e:
        return JSONResponse({"message": f"Cannot create request folder: {e}"}, status_code=500)

    form = await request.form()
    question_text = None
    saved_files = {}

    # Save all uploaded files to the request folder
    for field_name, value in form.items():
        if hasattr(value, "filename") and value.filename:
            file_path = os.path.join(request_folder, value.filename)
            try:
                async with aiofiles.open(file_path, "wb") as f:
                    await f.write(await value.read())
                saved_files[field_name] = file_path

                if field_name == "questions.txt":
                    async with aiofiles.open(file_path, "r") as f:
                        question_text = await f.read()
            except Exception as e:
                return JSONResponse({"message": f"File save error: {e}"}, status_code=500)
        else:
            saved_files[field_name] = value

    # Fallback: If no questions.txt, use the first file as question
    if question_text is None and saved_files:
        first_file = next(iter(saved_files.values()))
        if isinstance(first_file, str) and os.path.exists(first_file):
            try:
                async with aiofiles.open(first_file, "r") as f:
                    question_text = await f.read()
            except:
                pass

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

        if execution_result["code"] != 1:
            return JSONResponse({"message": "Error occurred while processing", "details": execution_result.get("output", "")})

        # Get answers from LLM
        gpt_ans = await answer_with_data(response["questions"], folder=request_folder)
        final_result = await run_python_code(gpt_ans["code"], gpt_ans["libraries"], folder=request_folder)

        # Handle final results
        if final_result["code"] == 1:
            result_path = os.path.join(request_folder, "result.json")
            if os.path.exists(result_path):
                with open(result_path, "r") as f:
                    data = json.load(f)
                return JSONResponse(content=data)
            else:
                return JSONResponse({"message": "Processing completed", "result": final_result["output"]})
        else:
            return JSONResponse({"message": "Failed to generate results", "details": final_result.get("output", "")})

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
    </head>
    <body>
        <h1>🤖 Data Analyst Agent</h1>
        <p>Your FastAPI application is running successfully on Vercel!</p>
        <form action="/web-api" method="post">
            <label for="question">Ask a question:</label><br>
            <textarea name="question" rows="4" cols="50" placeholder="What are the top 10 movies by box office?"></textarea><br>
            <button type="submit">Analyze</button>
        </form>
    </body>
    </html>
    """

@app.post("/web-api")
async def web_analyze(question: str = Form(...)):
    """Web interface endpoint"""
    base_upload_dir = ensure_upload_dir()
    request_id = str(uuid.uuid4())
    request_folder = os.path.join(base_upload_dir, request_id)
    
    try:
        os.makedirs(request_folder, exist_ok=True)
        question_file = os.path.join(request_folder, "questions.txt")
        
        async with aiofiles.open(question_file, "w") as f:
            await f.write(question)
        
        return {"question": question, "status": "received", "message": "Question processed successfully"}
        
    except Exception as e:
        return {"question": question, "error": f"Processing error: {str(e)}"}





# For local development
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
