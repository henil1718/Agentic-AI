import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel
from supabase import Client, create_client

load_dotenv(Path(__file__).with_name(".env"))

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

if not supabase_url or not supabase_key:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in backend/.env")

supabase: Client = create_client(supabase_url, supabase_key)

class ArchitectSchema(BaseModel):
    goal: str
    constraints: list[str]
    tech_stack: list[str]

def _save_agent_log(run_id: str, agent_role: str, payload: dict[str, Any]) -> None:
    supabase.table("agent_logs").insert(
        {"run_id": run_id, "agent_role": agent_role, "payload": payload}
    ).execute()

def _groq_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY (for Groq) is missing.")
    return OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )

def agent_1_architect(prompt: str, run_id: str) -> ArchitectSchema:
    time.sleep(1)
    try:
        client = _groq_client()
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Analyze the requested software task. Return a JSON object with "
                        "exactly three fields: a string 'goal', a list of strings "
                        "'constraints', and a list of strings 'tech_stack'."
                    )
                },
                {"role": "user", "content": f"Task: {prompt}"},
            ],
            response_format={"type": "json_object"},
        )
        result = ArchitectSchema.model_validate_json(response.choices[0].message.content)
        _save_agent_log(run_id, "architect", result.model_dump())
        return result
    except Exception as e:
        _save_agent_log(run_id, "architect", {"error": str(e)})
        raise e

def agent_2_coder(schema: ArchitectSchema, run_id: str) -> dict[str, str]:
    time.sleep(1)
    try:
        client = _groq_client()
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Generate the implementation and dependency list from the "
                        "architect's schema. Return a JSON object with exactly two "
                        "string fields: 'main.py' and 'requirements.txt'. Put complete "
                        "source code in main.py and newline-separated packages in "
                        "requirements.txt."
                    ),
                },
                {
                    "role": "user",
                    "content": schema.model_dump_json(indent=2),
                },
            ],
            response_format={"type": "json_object"},
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Ensure fallback keys if the LLM slightly deviates
        main_py = result.get("main.py") or result.get("main_py") or result.get("main") or ""
        requirements = result.get("requirements.txt") or result.get("requirements") or ""
        
        final_artifacts = {"main.py": str(main_py), "requirements.txt": str(requirements)}
        _save_agent_log(run_id, "coder", final_artifacts)
        return final_artifacts
    except Exception as e:
        _save_agent_log(run_id, "coder", {"error": str(e), "main.py": "Execution failed."})
        raise e

def agent_3_deployer(artifacts: dict[str, str], run_id: str) -> dict[str, Any]:
    time.sleep(1)
    try:
        client = _groq_client()
        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Review the supplied code and requirements as a deployment "
                        "readiness simulation. Return a JSON object detailing "
                        "container readiness and port status, including readiness, "
                        "port, port_status, and any relevant checks or notes. Do not "
                        "claim that a real deployment or container was run."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(artifacts, indent=2),
                },
            ],
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        _save_agent_log(run_id, "deployer", result)
        return result
    except Exception as e:
        _save_agent_log(run_id, "deployer", {"error": str(e)})
        raise e