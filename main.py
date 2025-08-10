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

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/api")
async def analyze(request: Request):
    # Create a unique folder for this request
    request_id = str(uuid.uuid4())
    request_folder = os.path.join(UPLOAD_DIR, request_id)
    os.makedirs(request_folder, exist_ok=True)

    form = await request.form()
    question_text = None
    saved_files = {}

    # Save all uploaded files to the request folder
    for field_name, value in form.items():
        if hasattr(value, "filename") and value.filename:  # It's a file
            file_path = os.path.join(request_folder, value.filename)
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(await value.read())
            saved_files[field_name] = file_path

            # If it's questions.txt, read its content
            if field_name == "questions.txt":
                async with aiofiles.open(file_path, "r") as f:
                    question_text = await f.read()
        else:
            saved_files[field_name] = value

    # Fallback: If no questions.txt, use the first file as question
    if question_text is None and saved_files:
        first_file = next(iter(saved_files.values()))
        async with aiofiles.open(first_file, "r") as f:
            question_text = await f.read()

    # Get code steps from LLM
    response = await parse_question_with_llm(
        question_text=question_text,
        uploaded_files=saved_files,
        folder=request_folder
    )

    print(response)

    # Execute generated code safely
    execution_result = await run_python_code(response["code"], response["libraries"], folder=request_folder)
    print(execution_result)

    count = 0
    while execution_result["code"] == 0 and count < 3:
        print(f"Error occurred while scraping x{count}")
        new_question_text = str(question_text) + "previous time this error occurred" + str(execution_result["output"])
        response = await parse_question_with_llm(
            question_text=new_question_text,
            uploaded_files=saved_files,
            folder=request_folder
        )
        print(response)
        execution_result = await run_python_code(response["code"], response["libraries"], folder=request_folder)
        print(execution_result)
        count += 1

    if execution_result["code"] == 1:
        execution_result = execution_result["output"]
    else:
        return JSONResponse({"message": "error occurred while scraping."})

    # Get answers from LLM
    gpt_ans = await answer_with_data(response["questions"], folder=request_folder)
    print(gpt_ans)

    # Executing code
    try:
        final_result = await run_python_code(gpt_ans["code"], gpt_ans["libraries"], folder=request_folder)
    except Exception as e:
        gpt_ans = await answer_with_data(response["questions"]+str("Please follow the json structure"), folder=request_folder)
        print("Trying after it caught under except block-wrong json format", gpt_ans)
        final_result = await run_python_code(gpt_ans["code"], gpt_ans["libraries"], folder=request_folder)

    count = 0
    json_str = 1
    while final_result["code"] == 0 and count < 3:
        print(f"Error occurred while executing code x{count}")
        new_question_text = str(response["questions"]) + "previous time this error occurred" + str(final_result["output"])
        if json_str == 0:
            new_question_text += "follow the structure {'code': '', 'libraries': ''}"
            
        gpt_ans = await answer_with_data(new_question_text, folder=request_folder)
        print(gpt_ans)

        try:
            json_str = 0
            final_result = await run_python_code(gpt_ans["code"], gpt_ans["libraries"], folder=request_folder)
            json_str = 1
        except Exception as e:
            print(f"Exception occurred: {e}")
            count -= 1

        print(final_result)
        count += 1

    if final_result["code"] == 1:
        final_result = final_result["output"]
    else:
        result_path = os.path.join(request_folder, "result.json")
        with open(result_path, "r") as f:
            data = json.load(f)
        return JSONResponse(content=data)

    result_path = os.path.join(request_folder, "result.json")
    with open(result_path, "r") as f:
        try:
            data = json.load(f)
            return JSONResponse(content=data)
        except Exception as e:
            return JSONResponse({"message": f"Error occurred while processing result.json: {e}"})

# Web interface route
@app.get("/", response_class=HTMLResponse)
async def web_interface():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>🎬 Data Analyst Agent</title>
        <style>
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                margin: 0; 
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                background: white;
                border-radius: 15px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.3);
                overflow: hidden;
            }
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 30px;
                text-align: center;
            }
            .content {
                padding: 30px;
            }
            textarea { 
                width: 100%; 
                padding: 15px; 
                border: 2px solid #e1e5e9;
                border-radius: 10px;
                font-size: 14px;
                resize: vertical;
                min-height: 120px;
                box-sizing: border-box;
            }
            .submit-btn { 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white; 
                padding: 15px 30px; 
                border: none; 
                border-radius: 10px;
                cursor: pointer; 
                font-size: 16px;
                font-weight: bold;
                margin-top: 15px;
            }
            .loading { 
                display: none; 
                color: #667eea; 
                margin-top: 15px;
                text-align: center;
            }
            .example {
                background: #f8f9fa;
                padding: 20px;
                border-radius: 10px;
                margin-bottom: 20px;
                border-left: 4px solid #667eea;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 Data Analyst Agent</h1>
                <p>Intelligent Data Analysis & Visualization Platform</p>
            </div>
            
            <div class="content">
                <div class="example">
                    <strong>💡 Try These Questions:</strong>
                    <ul>
                        <li>What are the top 10 highest-grossing movies worldwide?</li>
                        <li>Show me a chart of Indian box office collections</li>
                        <li>Compare movie ratings between different genres</li>
                        <li>What are the trending topics on social media?</li>
                    </ul>
                </div>
                
                <form action="/web-api" method="post" enctype="multipart/form-data" onsubmit="showLoading()">
                    <label><strong>🎯 Your Data Analysis Question:</strong></label><br><br>
                    <textarea name="question" placeholder="Ask any data analysis question...

Example: What are the top 10 movies by box office collection in India?"></textarea><br>
                    
                    <button type="submit" class="submit-btn">🔍 Analyze Data</button>
                    <div class="loading" id="loading">
                        ⏳ Processing your question... This may take up to 3 minutes.
                    </div>
                </form>
            </div>
        </div>
        
        <script>
            function showLoading() {
                document.getElementById('loading').style.display = 'block';
            }
        </script>
    </body>
    </html>
    """

@app.post("/web-api")
async def web_analyze(question: str = Form(...)):
    # Create a unique folder for this web request
    request_id = str(uuid.uuid4())
    request_folder = os.path.join(UPLOAD_DIR, request_id)
    os.makedirs(request_folder, exist_ok=True)
    
    # Create a temporary questions.txt file
    question_file = os.path.join(request_folder, "questions.txt")
    async with aiofiles.open(question_file, "w") as f:
        await f.write(question)
    
    saved_files = {"questions.txt": question_file}
    
    try:
        # Use your existing LLM processing logic
        response = await parse_question_with_llm(
            question_text=question,
            uploaded_files=saved_files,
            folder=request_folder
        )
        
        # Execute the generated code
        execution_result = await run_python_code(response["code"], response["libraries"], folder=request_folder)
        
        if execution_result["code"] == 1:
            # Get final answer
            gpt_ans = await answer_with_data(response["questions"], folder=request_folder)
            final_result = await run_python_code(gpt_ans["code"], gpt_ans["libraries"], folder=request_folder)
            
            if final_result["code"] == 1:
                # Try to read result.json if it exists
                result_path = os.path.join(request_folder, "result.json")
                if os.path.exists(result_path):
                    with open(result_path, "r") as f:
                        data = json.load(f)
                    return {"question": question, "result": data}
                else:
                    return {"question": question, "result": final_result["output"]}
            else:
                return {"question": question, "error": "Failed to generate final answer"}
        else:
            return {"question": question, "error": "Failed to process question"}
            
    except Exception as e:
        return {"question": question, "error": f"Processing error: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
