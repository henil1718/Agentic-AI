import json
import os
import time
import requests
from pathlib import Path
from typing import Any, TypedDict

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel
from supabase import Client, create_client
from langgraph.graph import StateGraph, START, END

load_dotenv(Path(__file__).with_name(".env"))

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

if not supabase_url or not supabase_key:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in backend/.env")

supabase: Client = create_client(supabase_url, supabase_key)

# Plain URL string (NOT a markdown link)
VERCEL_DEPLOY_URL = "https://api.vercel.com/v13/deployments"


def _save_agent_log(run_id: str, agent_role: str, payload: dict[str, Any]) -> None:
    supabase.table("agent_logs").insert(
        {"run_id": run_id, "agent_role": agent_role, "payload": payload}
    ).execute()


def _get_client(role: str) -> OpenAI:
    env_map = {
        "architect": "ARCHITECT_API_KEY",
        "coder": "CODER_API_KEY",
        "deployer": "DEPLOYER_API_KEY"
    }
    key_name = env_map.get(role)
    api_key = os.getenv(key_name) or os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise ValueError(f"{key_name} and OPENAI_API_KEY are missing.")

    return OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")


# --- 1. Define the Global State ---
class HandoffState(TypedDict):
    run_id: str
    prompt: str
    architect_schema: str
    artifacts: dict
    feedback: str
    retry_count: int
    is_approved: bool


# --- 2. Define the Nodes ---
def architect_node(state: HandoffState):
    time.sleep(1)
    client = _get_client("architect")

    # Force the Architect to ONLY use React/Vite so it doesn't confuse the Coder
    system_content = (
        "You are an Expert Software Architect designing a technical specification for a downstream Coder agent. "
        "CRITICAL: The tech stack MUST ALWAYS be React and Vite. Do not use vanilla HTML/JS. "
        "Return a strictly formatted JSON object with exactly three fields: "
        "1. 'goal', 2. 'constraints', 3. 'tech_stack'. "
        "Output ONLY valid JSON."
    )

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"Task: {state['prompt']}"},
        ],
        response_format={"type": "json_object"},
    )

    schema_dict = json.loads(response.choices[0].message.content)
    _save_agent_log(state["run_id"], "architect", schema_dict)

    return {"architect_schema": json.dumps(schema_dict, indent=2)}


def coder_node(state: HandoffState):
    time.sleep(1)
    client = _get_client("coder")
    current_retries = state.get("retry_count", 0)

    # Explicitly demand JSON escaping and React structure
    system_content = (
        "You are an Expert Senior Developer. "
        "CRITICAL CONSTRAINTS: "
        "1. Return ONLY a raw JSON object with a single key 'files', mapping filenames to source code strings. "
        "2. You MUST build a React + Vite application. Do NOT generate vanilla HTML/CSS/JS. "
        "3. Required files: 'package.json', 'index.html', 'src/main.tsx', 'src/App.tsx', and 'vite.config.js'. "
        "4. You MUST properly escape all double quotes (\\\") and newlines (\\n) inside your code strings so the JSON does not break. "
        "5. Output ONLY valid JSON. DO NOT wrap in markdown."
    )

    if state.get("feedback"):
        system_content += f"\n\nCRITICAL FIX REQUIRED: {state['feedback']}"

    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": state["architect_schema"]},
            ],
            response_format={"type": "json_object"},
            max_tokens=6000,
            temperature=0.2
        )

        raw_output = response.choices[0].message.content.strip()

        start_idx = raw_output.find('{')
        end_idx = raw_output.rfind('}')
        clean_json_str = (
            raw_output[start_idx:end_idx + 1]
            if (start_idx != -1 and end_idx != -1 and end_idx > start_idx)
            else raw_output
        )

        result = json.loads(clean_json_str)
        files = result.get("files", result)

        return {"artifacts": {"files": files}, "retry_count": current_retries + 1, "feedback": ""}

    except Exception as e:
        error_msg = str(e)
        print(f"Coder Node Attempt {current_retries + 1} Failed: {error_msg}")

        feedback_msg = (
            "Your JSON output was invalid or truncated. Ensure you escape all double quotes and output a valid JSON object."
        )

        return {
            "artifacts": {"files": {"error.log": f"Failed: {error_msg}"}},
            "retry_count": current_retries + 1,
            "feedback": feedback_msg,
            "is_approved": False
        }


def reviewer_node(state: HandoffState):
    if not state.get("artifacts") or "error.log" in state["artifacts"].get("files", {}):
        return {"is_approved": False}

    client = _get_client("coder")
    system_content = (
        "You are a strict Senior Staff Engineer reviewing code generated by a developer. "
        "Return a JSON object with two fields: "
        "1. 'is_approved': a boolean. "
        "2. 'feedback': a string detailing what needs to be fixed (leave empty if approved)."
    )

    prompt = f"Architect Requirements:\n{state['architect_schema']}\n\nGenerated Files:\n{json.dumps(state['artifacts'], indent=2)}"

    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    review = json.loads(response.choices[0].message.content)
    return {"is_approved": review.get("is_approved", False), "feedback": review.get("feedback", "")}


def _build_package_json(coder_package_json: Any) -> str:
    """Merge the Coder's package.json with the dependencies Vercel needs to build."""
    base_deps = {
        "react": "^18.2.0",
        "react-dom": "^18.2.0",
        "lucide-react": "^0.300.0",
    }
    base_dev_deps = {
        "@vitejs/plugin-react": "^4.2.1",
        "vite": "^5.0.0",
    }

    user_deps: dict = {}
    user_dev_deps: dict = {}
    try:
        if isinstance(coder_package_json, str):
            parsed = json.loads(coder_package_json)
        elif isinstance(coder_package_json, dict):
            parsed = coder_package_json
        else:
            parsed = {}
        if isinstance(parsed.get("dependencies"), dict):
            user_deps = parsed["dependencies"]
        if isinstance(parsed.get("devDependencies"), dict):
            user_dev_deps = parsed["devDependencies"]
    except Exception:
        pass  # Coder's package.json was unusable; fall back to base only

    # Base versions win so core packages stay compatible; extras from the Coder are kept
    return json.dumps({
        "name": "handoff-os-app",
        "private": True,
        "version": "1.0.0",
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "preview": "vite preview"
        },
        "dependencies": {**user_deps, **base_deps},
        "devDependencies": {**user_dev_deps, **base_dev_deps},
    }, indent=2)


def deployer_node(state: HandoffState):
    time.sleep(1)
    result: dict[str, Any] = {}

    try:
        client = _get_client("deployer")

        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=[
                {
                    "role": "system",
                    "content": "You are an Expert DevOps Engineer. Return a JSON object with: 'readiness', 'deployment_notes'."
                },
                {"role": "user", "content": json.dumps(state["artifacts"], indent=2)},
            ],
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
    except Exception as e:
        # Notes are nice-to-have; don't let them block the actual deployment
        print(f"Deployer notes generation failed: {e}")
        result = {"readiness": "Unknown", "notes_error": str(e)}

    vercel_token = os.getenv("VERCEL_TOKEN")
    if not vercel_token:
        result["deployment_error"] = "VERCEL_TOKEN missing from environment."
        _save_agent_log(state["run_id"], "deployer", result)
        return {}

    files_payload = []
    generated_files = state["artifacts"].get("files", {})

    if "package.json" not in generated_files:
        generated_files["package.json"] = "{}"
    if "vite.config.js" not in generated_files and "vite.config.ts" not in generated_files:
        generated_files["vite.config.js"] = ""

    for filename, content in generated_files.items():
        if isinstance(content, (dict, list)):
            content = json.dumps(content, indent=2)

        if isinstance(content, str):
            content = content.strip()
            if content.startswith("```"):
                lines = content.split('\n')
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = '\n'.join(lines).strip()

            if filename == "package.json":
                content = _build_package_json(content)

            if filename in ["vite.config.js", "vite.config.ts", "vite.config.mjs"]:
                content = (
                    "import { defineConfig } from 'vite';\n"
                    "import react from '@vitejs/plugin-react';\n\n"
                    "export default defineConfig({\n"
                    "  plugins: [react()],\n"
                    "});"
                )

        files_payload.append({
            "file": filename,
            "data": content
        })

    headers = {
        "Authorization": f"Bearer {vercel_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "name": "handoff-os-deployment",
        "files": files_payload,
        "projectSettings": {
            "framework": "vite"
        }
    }

    try:
        api_response = requests.post(
            VERCEL_DEPLOY_URL, headers=headers, json=payload, timeout=60
        )
        api_response.raise_for_status()
        deployment_data = api_response.json()

        result["live_url"] = f"https://{deployment_data.get('url')}"
        result["vercel_deployment_id"] = deployment_data.get("id")

    except requests.exceptions.RequestException as e:
        result["deployment_error"] = str(e)
        if hasattr(e, 'response') and e.response is not None:
            result["deployment_details"] = e.response.text

    _save_agent_log(state["run_id"], "deployer", result)

    return {}


# --- 3. Define Routing Logic ---
def route_after_review(state: HandoffState):
    if state["is_approved"] or state["retry_count"] >= 3:
        _save_agent_log(state["run_id"], "coder", state["artifacts"])
        return "deployer"
    return "coder"


# --- 4. Build the Graph ---
workflow = StateGraph(HandoffState)

workflow.add_node("architect", architect_node)
workflow.add_node("coder", coder_node)
workflow.add_node("reviewer", reviewer_node)
workflow.add_node("deployer", deployer_node)

workflow.add_edge(START, "architect")
workflow.add_edge("architect", "coder")
workflow.add_edge("coder", "reviewer")
workflow.add_conditional_edges("reviewer", route_after_review)
workflow.add_edge("deployer", END)

app_graph = workflow.compile()


# --- 5. Export Execution Function ---
def run_agent_graph(prompt: str, run_id: str):
    initial_state = {
        "run_id": run_id,
        "prompt": prompt,
        "retry_count": 0,
        "feedback": "",
        "is_approved": False
    }
    try:
        app_graph.invoke(initial_state)
    except Exception as e:
        print(f"Graph execution failed: {e}")