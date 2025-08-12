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

    # Execute generated code safely
    execution_result = await run_python_code(response["code"], response["libraries"], folder=request_folder)

    count = 0
    while execution_result["code"] == 0 and count < 3:
        print(f"Error occurred while scraping x{count}")
        new_question_text = str(question_text) + "previous time this error occurred" + str(execution_result["output"])
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
        return JSONResponse({"message": "error occurred while scraping."})

    # Get answers from LLM
    gpt_ans = await answer_with_data(response["questions"], folder=request_folder)

    # Executing code
    try:
        final_result = await run_python_code(gpt_ans["code"], gpt_ans["libraries"], folder=request_folder)
    except Exception as e:
        gpt_ans = await answer_with_data(response["questions"]+str("Please follow the json structure"), folder=request_folder)
        final_result = await run_python_code(gpt_ans["code"], gpt_ans["libraries"], folder=request_folder)

    count = 0
    json_str = 1
    while final_result["code"] == 0 and count < 3:
        print(f"Error occurred while executing code x{count}")
        new_question_text = str(response["questions"]) + "previous time this error occurred" + str(final_result["output"])
        if json_str == 0:
            new_question_text += "follow the structure {'code': '', 'libraries': ''}"
            
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
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }
            
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }
            
            .container {
                max-width: 1000px;
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
            
            .header h1 {
                font-size: 2.5em;
                margin-bottom: 10px;
                text-shadow: 0 2px 4px rgba(0,0,0,0.3);
            }
            
            .header p {
                font-size: 1.2em;
                opacity: 0.9;
            }
            
            .content {
                padding: 30px;
            }
            
            .example-box {
                background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
                padding: 25px;
                border-radius: 10px;
                margin-bottom: 25px;
                border-left: 5px solid #667eea;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            
            .example-box h3 {
                color: #495057;
                margin-bottom: 15px;
                font-size: 1.3em;
            }
            
            .example-list {
                list-style: none;
                padding: 0;
            }
            
            .example-list li {
                padding: 8px 0;
                color: #6c757d;
                font-size: 1em;
                border-bottom: 1px solid rgba(102, 126, 234, 0.1);
                cursor: pointer;
                transition: all 0.3s ease;
            }
            
            .example-list li:hover {
                color: #667eea;
                transform: translateX(5px);
            }
            
            .example-list li:last-child {
                border-bottom: none;
            }
            
            .form-section {
                background: #fff;
                padding: 25px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.05);
            }
            
            .form-label {
                display: block;
                font-weight: 600;
                color: #495057;
                margin-bottom: 10px;
                font-size: 1.1em;
            }
            
            .question-input {
                width: 100%;
                min-height: 120px;
                padding: 15px;
                border: 2px solid #e9ecef;
                border-radius: 10px;
                font-size: 16px;
                font-family: inherit;
                resize: vertical;
                transition: border-color 0.3s ease;
                background: #fff;
            }
            
            .question-input:focus {
                outline: none;
                border-color: #667eea;
                box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
            }
            
            .submit-btn {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 15px 30px;
                border: none;
                border-radius: 10px;
                cursor: pointer;
                font-size: 16px;
                font-weight: 600;
                margin-top: 20px;
                transition: all 0.3s ease;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            
            .submit-btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
            }
            
            .submit-btn:active {
                transform: translateY(0);
            }
            
            .loading {
                display: none;
                text-align: center;
                margin-top: 20px;
                color: #667eea;
                font-style: italic;
            }
            
            .spinner {
                border: 3px solid #f3f3f3;
                border-top: 3px solid #667eea;
                border-radius: 50%;
                width: 30px;
                height: 30px;
                animation: spin 1s linear infinite;
                margin: 10px auto;
            }
            
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            
            .result-container {
                margin-top: 30px;
                padding: 25px;
                background: #f8f9fa;
                border-radius: 10px;
                display: none;
                box-shadow: 0 2px 10px rgba(0,0,0,0.05);
            }
            
            .result-container h3 {
                color: #495057;
                margin-bottom: 15px;
            }
            
            .result-content {
                background: white;
                padding: 20px;
                border-radius: 8px;
                border-left: 4px solid #28a745;
            }
            
            .error-content {
                border-left-color: #dc3545;
                background: #fff5f5;
            }
            
            .api-info {
                background: linear-gradient(135deg, #17a2b8 0%, #138496 100%);
                color: white;
                padding: 20px;
                margin-top: 20px;
                border-radius: 10px;
                text-align: center;
            }
            
            .api-info code {
                background: rgba(255,255,255,0.2);
                padding: 2px 6px;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
            }
            
            @media (max-width: 768px) {
                .container {
                    margin: 10px;
                    border-radius: 10px;
                }
                
                .content {
                    padding: 20px;
                }
                
                .header {
                    padding: 20px;
                }
                
                .header h1 {
                    font-size: 2em;
                }
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
                            placeholder="Type your data analysis question here...

Examples:
• What are the top 10 movies by IMDb rating?
• Analyze the correlation between movie budget and box office success
• Create a chart showing population growth in major cities
• Find trending hashtags on Twitter today"
                            required
                        ></textarea>
                        
                        <button type="submit" class="submit-btn">🔍 Analyze Data</button>
                        
                        <div class="loading" id="loading">
                            <div class="spinner"></div>
                            <p>⏳ Processing your question... This may take up to 3 minutes while I analyze the data and generate insights.</p>
                        </div>
                    </form>
                </div>
                
                <div class="result-container" id="resultContainer">
                    <h3>📊 Analysis Results</h3>
                    <div id="resultContent" class="result-content"></div>
                </div>
                
                <div class="api-info">
                    <h3>🔗 API Access</h3>
                    <p>You can also access this Data Analyst Agent programmatically:</p>
                    <p><strong>Endpoint:</strong> <code>POST /api</code></p>
                    <p><strong>Usage:</strong> <code>curl -X POST your-url/api -F "questions.txt=@your_question.txt"</code></p>
                </div>
            </div>
        </div>
        
        <script>
            function fillQuestion(text) {
                document.getElementById('questionInput').value = text;
                document.getElementById('questionInput').focus();
            }
            
            function submitQuestion(event) {
                event.preventDefault();
                
                const questionInput = document.getElementById('questionInput');
                const question = questionInput.value.trim();
                
                if (!question) {
                    alert('Please enter a question before submitting.');
                    return;
                }
                
                // Show loading state
                document.getElementById('loading').style.display = 'block';
                document.getElementById('resultContainer').style.display = 'none';
                
                // Create form data
                const formData = new FormData();
                formData.append('question', question);
                
                // Submit request
                fetch('/web-api', {
                    method: 'POST',
                    body: formData
                })
                .then(response => response.json())
                .then(data => {
                    displayResults(data);
                })
                .catch(error => {
                    console.error('Error:', error);
                    displayError('Network error occurred. Please try again.');
                })
                .finally(() => {
                    document.getElementById('loading').style.display = 'none';
                });
            }
            
            function displayResults(data) {
                const container = document.getElementById('resultContent');
                const resultContainer = document.getElementById('resultContainer');
                
                container.className = 'result-content'; // Reset classes
                
                if (data.error) {
                    container.className += ' error-content';
                    container.innerHTML = `
                        <h4>❌ Error Occurred</h4>
                        <p><strong>Error:</strong> ${data.error}</p>
                        <p><strong>Question:</strong> ${data.question}</p>
                        ${data.details ? `<p><strong>Details:</strong> ${data.details}</p>` : ''}
                    `;
                } else if (data.result) {
                    let html = `<h4>📝 Question: ${data.question}</h4>`;
                    
                    // Handle array responses (like your movie analysis)
                    if (Array.isArray(data.result)) {
                        html += '<h4>📊 Results:</h4><ol>';
                        data.result.forEach((item, index) => {
                            if (typeof item === 'string' && item.startsWith('data:image/')) {
                                html += `<li><strong>Visualization:</strong><br><img src="${item}" style="max-width: 100%; margin-top: 10px; border-radius: 5px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);"></li>`;
                            } else {
                                html += `<li>${item}</li>`;
                            }
                        });
                        html += '</ol>';
                    }
                    // Handle object responses
                    else if (typeof data.result === 'object') {
                        if (data.result.top_10_movies) {
                            html += '<h4>🎬 Top Movies:</h4><div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px; margin: 15px 0;">';
                            data.result.top_10_movies.forEach((movie, index) => {
                                html += `
                                    <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid #667eea;">
                                        <strong>#${index + 1} ${movie.Title}</strong><br>
                                        💰 Box Office: ₹${movie.BoxOfficeCollection} Crores
                                    </div>
                                `;
                            });
                            html += '</div>';
                        }
                        
                        if (data.result.plot_base64) {
                            html += `
                                <h4>📈 Visualization:</h4>
                                <img src="data:image/png;base64,${data.result.plot_base64}" 
                                     style="max-width: 100%; margin-top: 15px; border-radius: 5px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);" 
                                     alt="Data Visualization">
                            `;
                        }
                        
                        // Fallback for other object structures
                        if (!data.result.top_10_movies && !data.result.plot_base64) {
                            html += `<pre style="background: #f8f9fa; padding: 15px; border-radius: 5px; overflow-x: auto; white-space: pre-wrap;">${JSON.stringify(data.result, null, 2)}</pre>`;
                        }
                    }
                    // Handle simple string responses
                    else {
                        html += `<p><strong>Result:</strong> ${data.result}</p>`;
                    }
                    
                    container.innerHTML = html;
                }
                
                resultContainer.style.display = 'block';
                resultContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
            
            function displayError(message) {
                const container = document.getElementById('resultContent');
                container.className = 'result-content error-content';
                container.innerHTML = `
                    <h4>❌ Error</h4>
                    <p>${message}</p>
                `;
                document.getElementById('resultContainer').style.display = 'block';
            }
        </script>
    </body>
    </html>
    """

@app.post("/web-api")
async def web_analyze(question: str = Form(...)):
    """
    Web interface endpoint for processing questions submitted via the form
    """
    # Create a unique folder for this web request
    request_id = str(uuid.uuid4())
    request_folder = os.path.join(UPLOAD_DIR, request_id)
    os.makedirs(request_folder, exist_ok=True)
    
    try:
        # Create a temporary questions.txt file
        question_file = os.path.join(request_folder, "questions.txt")
        async with aiofiles.open(question_file, "w") as f:
            await f.write(question)
        
        saved_files = {"questions.txt": question_file}
        
        # Use the same LLM processing logic as the main API
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
                    return {"question": question, "result": data, "status": "success"}
                else:
                    return {"question": question, "result": final_result["output"], "status": "success"}
            else:
                return {"question": question, "error": "Failed to generate final answer", "details": final_result.get("output", "")}
        else:
            return {"question": question, "error": "Failed to process question", "details": execution_result.get("output", "")}
            
    except Exception as e:
        return {"question": question, "error": f"Processing error: {str(e)}"}

# Add handler for Vercel compatibility
handler = app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
