import uuid
from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from agent_pipeline import agent_1_architect, agent_2_coder, agent_3_deployer

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

def run_pipeline(prompt: str, run_id: str):
    try:
        schema = agent_1_architect(prompt, run_id)
        artifacts = agent_2_coder(schema, run_id)
        agent_3_deployer(artifacts, run_id)
    except Exception as e:
        print(f"Pipeline failed: {e}")

@app.post("/api/trigger")
async def trigger_pipeline(
    request: TriggerRequest, background_tasks: BackgroundTasks
) -> dict[str, str]:
    run_id = str(uuid.uuid4())
    background_tasks.add_task(run_pipeline, request.prompt, run_id)
    return {"status": "Pipeline started", "run_id": run_id}