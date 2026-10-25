import io
import uuid
import zipfile
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Import the LangGraph executor and supabase client
from agent_pipeline import run_agent_graph, supabase

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TriggerRequest(BaseModel):
    prompt: str

@app.post("/api/trigger")
async def trigger_pipeline(
    request: TriggerRequest, background_tasks: BackgroundTasks
) -> dict[str, str]:
    run_id = str(uuid.uuid4())
    # Kick off the LangGraph state machine in the background
    background_tasks.add_task(run_agent_graph, request.prompt, run_id)
    return {"status": "Pipeline started", "run_id": run_id}

@app.get("/api/status/{run_id}")
async def get_deployment_status(run_id: str):
    """Checks Supabase for the Deployer's log to fetch the live URL."""
    response = supabase.table("agent_logs").select("payload").eq("run_id", run_id).eq("agent_role", "deployer").execute()

    if not response.data:
        return {"status": "Deploying or waiting in queue..."}

    payload = response.data[0].get("payload", {})

    if "deployment_error" in payload:
        return {"status": "Failed", "error": payload["deployment_error"]}

    return {
        "status": "Success",
        "live_url": payload.get("live_url"),
        "vercel_deployment_id": payload.get("vercel_deployment_id")
    }

@app.get("/api/download/{run_id}")
async def download_code(run_id: str):
    """Fetches generated files from Supabase and returns them as a ZIP archive."""
    response = supabase.table("agent_logs").select("payload").eq("run_id", run_id).eq("agent_role", "coder").execute()

    if not response.data:
        raise HTTPException(status_code=404, detail="Run ID not found or Coder has not finished yet.")

    payload = response.data[0].get("payload", {})
    files = payload.get("files", {})

    if not files or "error.log" in files:
        raise HTTPException(status_code=400, detail="No valid code files available to download.")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for filename, content in files.items():
            zip_file.writestr(filename, content)

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": f"attachment; filename=HandoffOS_{run_id[:8]}.zip"}
    )