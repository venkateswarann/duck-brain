"""AI Agent Copilot routes for Script Generation & Assistant Chat."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _build_system_context(request: Request) -> str:
    """Build detailed system context including robot hardware state and MCP tools."""
    duck = request.app.state.duck
    joints_info = []
    for name, j in duck.joints.items():
        joints_info.append(f"- {name}: ID={j.id}, Range=[{j.min}, {j.max}] rad")
    joints_str = "\n".join(joints_info) if joints_info else "No joints configured."

    # MCP server tools context
    mcp_tools = [
        "servo_status: Check online status and positions of all configured servos.",
        "servo_scan: Scan the serial bus for all responding servo IDs (1-253).",
        "servo_set_id: Change a servo's ID and configure PID defaults.",
        "pinout: Read or update Raspberry Pi / Jetson GPIO pin mapping schema.",
        "gpio_write: Toggle or PWM output to configured GPIO pins.",
        "run_script: Start a Python script node under robot_scripts/.",
        "stop_script: Stop a running Python script node.",
        "system_metrics: Query host CPU, memory, temperature, and node resource locks.",
        "camera_stream: Stream MJPEG frames from video.capture node or Python script.",
    ]
    mcp_str = "\n".join([f"- {t}" for t in mcp_tools])

    return f"""You are the DCS AI Copilot & Hardware Assistant for the Open Duck Mini Robot system.
Your mission is to help the user write, debug, and optimize Python scripts for controlling the robot hardware, reading sensors, and interacting with DCS services.

ROBOT ENVIRONMENT:
- Robot ID: {duck.robot_id} ({duck.robot_name})
- Mock Hardware: {duck.mock_hardware}
- Serial Port: {duck.serial_port} (Baudrate: {duck.baudrate})
- Configured Joints:
{joints_str}

AVAILABLE MCP TOOLS & API ENDPOINTS:
{mcp_str}

PYTHON SCRIPTING GUIDELINES:
1. Python scripts run as independent nodes inside `robot_scripts/`.
2. Scripts can make HTTP calls to local DCS endpoints at `http://127.0.0.1:8000/api/...` or use standard Python libraries.
3. Scripts can read/write GPIO pins via `/api/gpio/write` or send commands to servos.
4. When writing code, provide clean, executable Python 3 code blocks (```python ... ```). Include brief comments explaining key logic.
5. If the user asks for reasoning or explanation, provide step-by-step thinking first.
"""


def _get_llm_url(base_url: str) -> str:
    """Normalize OpenAI-compatible endpoint URL."""
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        if url.endswith("/v1"):
            url = f"{url}/chat/completions"
        else:
            url = f"{url}/v1/chat/completions"
    return url


@router.post("/test")
async def test_llm_connection(request: Request):
    """Test LLM connection with configured endpoint & API key."""
    duck = request.app.state.duck
    endpoint = duck.llm_endpoint
    api_key = duck.llm_api_key
    model = duck.llm_model

    if not endpoint:
        raise HTTPException(400, "llm_endpoint is empty. Configure it in Settings -> LLM Agent.")

    target_url = _get_llm_url(endpoint)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Respond with 'DCS AI Connected' if you receive this."},
        ],
        "max_tokens": 100,
        "temperature": 0.2,
    }

    if "nemotron" in model.lower() or "nvidia" in model.lower() or "deepseek" in model.lower():
        payload["extra_body"] = {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": 2048,
        }

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(target_url, json=payload, headers=headers)
            if resp.status_code != 200:
                return {
                    "ok": False,
                    "status_code": resp.status_code,
                    "error": f"HTTP {resp.status_code}: {resp.text[:300]}",
                }
            data = resp.json()
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {}).get("content", "")
            return {
                "ok": True,
                "status_code": 200,
                "model": model,
                "endpoint": target_url,
                "reply": msg,
            }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/chat")
async def chat_with_agent(request: Request):
    """Chat endpoint for AI Script Assistant."""
    duck = request.app.state.duck
    body = await request.json()

    user_prompt = str(body.get("prompt", "")).strip()
    current_script = body.get("current_script")
    script_path = body.get("script_path")
    history = body.get("history") or []

    if not user_prompt:
        raise HTTPException(400, "prompt is required")

    endpoint = duck.llm_endpoint
    api_key = duck.llm_api_key
    model = duck.llm_model

    if not endpoint:
        raise HTTPException(400, "llm_endpoint is empty. Please set up LLM Agent in Settings page.")

    target_url = _get_llm_url(endpoint)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    system_context = _build_system_context(request)
    if script_path and current_script is not None:
        system_context += f"\n\nCURRENTLY OPENED SCRIPT (`{script_path}`):\n```python\n{current_script}\n```\n"

    messages = [{"role": "system", "content": system_context}]
    for msg in history:
        if isinstance(msg, dict) and "role" in msg and "content" in msg:
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_prompt})

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(duck.llm_temperature or 0.7),
        "max_tokens": int(duck.llm_max_tokens or 8192),
    }

    # Add NVIDIA Nemotron / DeepSeek reasoning parameters if applicable
    if "nemotron" in model.lower() or "nvidia" in model.lower() or "deepseek" in model.lower():
        payload["extra_body"] = {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": min(16384, int(duck.llm_max_tokens or 8192)),
        }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(target_url, json=payload, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(
                    resp.status_code,
                    f"LLM Provider Error (HTTP {resp.status_code}): {resp.text[:500]}",
                )
            data = resp.json()
            choice = data.get("choices", [{}])[0]
            message_obj = choice.get("message", {})
            content = message_obj.get("content", "")
            reasoning = message_obj.get("reasoning_content") or choice.get("reasoning_content")

            return {
                "ok": True,
                "model": model,
                "content": content,
                "reasoning": reasoning,
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Error communicating with LLM endpoint: {exc}") from exc
