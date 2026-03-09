"""
Nova Sonic voice assistant session manager.
Uses aws-sdk-bedrock-runtime (Smithy SDK) for HTTP/2 bidirectional streaming.
Uses Nova Sonic tool calling (not text markers) to trigger actions.

Flow for tool use:
  Model sends toolUse event → contentEnd(type=TOOL)
  Client executes tool → sends contentStart(TOOL) + toolResult + contentEnd
  Model generates spoken response based on tool result
"""

import asyncio
import base64
import json
import logging
import os
import uuid
from typing import Any, Callable

import boto3
from aws_sdk_bedrock_runtime.client import (
    BedrockRuntimeClient,
    InvokeModelWithBidirectionalStreamOperationInput,
)
from aws_sdk_bedrock_runtime.config import Config
from aws_sdk_bedrock_runtime.models import (
    BidirectionalInputPayloadPart,
    InvokeModelWithBidirectionalStreamInputChunk,
)
from smithy_aws_core.identity.components import AWSCredentialsIdentity, AWSIdentityProperties
from smithy_core.aio.interfaces.identity import IdentityResolver

import database
import violation_engine

logger = logging.getLogger(__name__)

NOVA_SONIC_MODEL_ID = "amazon.nova-2-sonic-v1:0"
INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000

SENTINEL_SYSTEM_PROMPT = """\
You are Sentinel, an autonomous compliance monitoring assistant integrated into \
a security dashboard. Speak in a professional but friendly tone. Keep every \
response to 2-3 sentences maximum.

You have access to tools to perform real actions. Use them when the user requests:
- Run / start / trigger a compliance scan → use runComplianceScan
- Check compliance score / status → use getComplianceScore
- Show / list violations → use getViolations
- Generate / export a report → use generateReport

Always call the appropriate tool rather than just describing what you would do.
After calling a tool, briefly summarise what happened based on the result.\
"""

# Tool schemas for promptStart
_EMPTY_SCHEMA = json.dumps({"type": "object", "properties": {}, "required": []})

SENTINEL_TOOLS = [
    {
        "toolSpec": {
            "name": "runComplianceScan",
            "description": (
                "Triggers a live compliance scan across all connected enterprise tools "
                "(HRMS, IT Admin, Procurement). Call this when the user asks to run, "
                "start, or trigger a scan."
            ),
            "inputSchema": {"json": _EMPTY_SCHEMA},
        }
    },
    {
        "toolSpec": {
            "name": "getComplianceScore",
            "description": (
                "Returns the current compliance score and open violation counts by severity. "
                "Call this when the user asks about the score, current status, or how things look."
            ),
            "inputSchema": {"json": _EMPTY_SCHEMA},
        }
    },
    {
        "toolSpec": {
            "name": "getViolations",
            "description": (
                "Returns the list of currently open compliance violations with details. "
                "Call this when the user asks what violations exist, or to list issues."
            ),
            "inputSchema": {"json": _EMPTY_SCHEMA},
        }
    },
    {
        "toolSpec": {
            "name": "generateReport",
            "description": (
                "Generates and exports a PDF compliance audit report. "
                "Call this when the user asks to generate, export, or download a report."
            ),
            "inputSchema": {"json": _EMPTY_SCHEMA},
        }
    },
]


class _BotoCredentialsResolver(IdentityResolver):
    """Wraps boto3's full credential chain (env vars, profiles, instance metadata, etc.)."""

    async def get_identity(self, *, properties: AWSIdentityProperties) -> AWSCredentialsIdentity:
        session = boto3.Session()
        creds = session.get_credentials()
        if creds is None:
            raise RuntimeError("No AWS credentials found")
        frozen = creds.get_frozen_credentials()
        return AWSCredentialsIdentity(
            access_key_id=frozen.access_key,
            secret_access_key=frozen.secret_key,
            session_token=frozen.token,
        )


def _make_client(region: str) -> BedrockRuntimeClient:
    config = Config(
        endpoint_uri=f"https://bedrock-runtime.{region}.amazonaws.com",
        region=region,
        aws_credentials_identity_resolver=_BotoCredentialsResolver(),
    )
    return BedrockRuntimeClient(config=config)


class VoiceSession:
    """Manages one Nova Sonic session for a connected WebSocket client."""

    def __init__(self) -> None:
        self._active = True
        self._prompt_name = str(uuid.uuid4())
        self._system_content = str(uuid.uuid4())
        self._audio_content = str(uuid.uuid4())
        # Tool call state (accumulated across events)
        self._tool_name: str = ""
        self._tool_use_id: str = ""
        self._tool_content: str = ""

    async def run(
        self,
        websocket: Any,
        on_action: Callable[[str, dict], Any] | None = None,
    ) -> None:
        region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        voice_id = os.environ.get("NOVA_SONIC_VOICE_ID", "matthew")
        client = _make_client(region)

        try:
            stream = await client.invoke_model_with_bidirectional_stream(
                InvokeModelWithBidirectionalStreamOperationInput(model_id=NOVA_SONIC_MODEL_ID)
            )
        except Exception as exc:
            logger.error("Nova Sonic stream failed: %s (%s)", exc, type(exc).__name__, exc_info=True)
            return

        async def send(payload: dict) -> None:
            try:
                event = InvokeModelWithBidirectionalStreamInputChunk(
                    value=BidirectionalInputPayloadPart(bytes_=json.dumps(payload).encode("utf-8"))
                )
                await stream.input_stream.send(event)
            except Exception as exc:
                logger.debug("Stream send error: %s", exc)

        # --- Session init ---
        await send({"event": {"sessionStart": {
            "inferenceConfiguration": {"maxTokens": 1024, "topP": 0.9, "temperature": 0.7}
        }}})

        await send({"event": {"promptStart": {
            "promptName": self._prompt_name,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": OUTPUT_SAMPLE_RATE,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "voiceId": voice_id,
                "encoding": "base64",
                "audioType": "SPEECH",
            },
            "toolUseOutputConfiguration": {"mediaType": "application/json"},
            "toolConfiguration": {"tools": SENTINEL_TOOLS},
        }}})

        # System prompt
        await send({"event": {"contentStart": {
            "promptName": self._prompt_name, "contentName": self._system_content,
            "type": "TEXT", "interactive": False, "role": "SYSTEM",
            "textInputConfiguration": {"mediaType": "text/plain"},
        }}})
        await send({"event": {"textInput": {
            "promptName": self._prompt_name, "contentName": self._system_content,
            "content": SENTINEL_SYSTEM_PROMPT,
        }}})
        await send({"event": {"contentEnd": {
            "promptName": self._prompt_name, "contentName": self._system_content,
        }}})

        # Greeting
        greeting_name = str(uuid.uuid4())
        await send({"event": {"contentStart": {
            "promptName": self._prompt_name, "contentName": greeting_name,
            "type": "TEXT", "interactive": False, "role": "USER",
            "textInputConfiguration": {"mediaType": "text/plain"},
        }}})
        await send({"event": {"textInput": {
            "promptName": self._prompt_name, "contentName": greeting_name,
            "content": "Please greet the user as Sentinel and ask what they'd like to do.",
        }}})
        await send({"event": {"contentEnd": {
            "promptName": self._prompt_name, "contentName": greeting_name,
        }}})

        # Start continuous audio input
        await send({"event": {"contentStart": {
            "promptName": self._prompt_name, "contentName": self._audio_content,
            "type": "AUDIO", "interactive": True, "role": "USER",
            "audioInputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": INPUT_SAMPLE_RATE,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "audioType": "SPEECH",
                "encoding": "base64",
            },
        }}})

        # --- Tool execution ---
        async def _execute_tool(tool_name: str, tool_use_id: str, tool_content: str) -> None:
            """Execute a Sentinel tool and send the result back to Nova Sonic."""
            result: dict = {}
            action_triggered: tuple | None = None

            try:
                if tool_name == "runComplianceScan":
                    scan_id = str(uuid.uuid4())
                    action_triggered = ("scan_started", {"scan_id": scan_id})
                    result = {
                        "status": "initiated",
                        "scan_id": scan_id,
                        "message": "Compliance scan has been triggered and is now running across all tools.",
                    }

                elif tool_name == "getComplianceScore":
                    score_data = violation_engine.calculate_compliance_score()
                    result = {
                        "score": score_data.get("score", 0),
                        "open_violations": score_data.get("open_violations", 0),
                        "by_severity": score_data.get("by_severity", {}),
                    }

                elif tool_name == "getViolations":
                    violations = database.get_violations()
                    open_v = [v for v in violations if v.get("status") == "open"]
                    result = {
                        "open_count": len(open_v),
                        "violations": [
                            {
                                "tool": v.get("tool_name", ""),
                                "type": v.get("violation_type", ""),
                                "username": v.get("username", ""),
                                "severity": v.get("severity", ""),
                            }
                            for v in open_v[:8]
                        ],
                    }

                elif tool_name == "generateReport":
                    action_triggered = ("generate_report", {})
                    result = {"status": "initiated", "message": "PDF report generation has been triggered."}

                else:
                    result = {"error": f"Unknown tool: {tool_name}"}

            except Exception as exc:
                logger.error("Tool %s execution error: %s", tool_name, exc)
                result = {"error": str(exc)}

            # Fire the frontend action before sending tool result
            if action_triggered and on_action:
                action, params = action_triggered
                await on_action(action, params)

            # Send tool result back to Nova Sonic
            tool_result_name = str(uuid.uuid4())
            await send({"event": {"contentStart": {
                "promptName": self._prompt_name,
                "contentName": tool_result_name,
                "interactive": False,
                "type": "TOOL",
                "role": "TOOL",
                "toolResultInputConfiguration": {
                    "toolUseId": tool_use_id,
                    "type": "TEXT",
                    "textInputConfiguration": {"mediaType": "text/plain"},
                },
            }}})
            await send({"event": {"toolResult": {
                "promptName": self._prompt_name,
                "contentName": tool_result_name,
                "content": json.dumps(result),
            }}})
            await send({"event": {"contentEnd": {
                "promptName": self._prompt_name,
                "contentName": tool_result_name,
            }}})

        # --- Receive mic audio from browser ---
        async def _receive_mic() -> None:
            try:
                while self._active:
                    try:
                        msg = await asyncio.wait_for(websocket.receive(), timeout=30)
                    except asyncio.TimeoutError:
                        continue
                    if msg["type"] == "websocket.disconnect":
                        break
                    if msg.get("bytes"):
                        b64 = base64.b64encode(msg["bytes"]).decode()
                        await send({"event": {"audioInput": {
                            "promptName": self._prompt_name,
                            "contentName": self._audio_content,
                            "content": b64,
                        }}})
                    elif msg.get("text"):
                        try:
                            ctrl = json.loads(msg["text"])
                            if ctrl.get("type") == "inject_context":
                                inject_name = str(uuid.uuid4())
                                await send({"event": {"contentStart": {
                                    "promptName": self._prompt_name, "contentName": inject_name,
                                    "type": "TEXT", "interactive": False, "role": "USER",
                                    "textInputConfiguration": {"mediaType": "text/plain"},
                                }}})
                                await send({"event": {"textInput": {
                                    "promptName": self._prompt_name, "contentName": inject_name,
                                    "content": ctrl.get("text", ""),
                                }}})
                                await send({"event": {"contentEnd": {
                                    "promptName": self._prompt_name, "contentName": inject_name,
                                }}})
                        except json.JSONDecodeError:
                            pass
            except Exception as exc:
                logger.debug("Mic receive loop ended: %s", exc)
            finally:
                self._active = False
                try:
                    await send({"event": {"contentEnd": {
                        "promptName": self._prompt_name, "contentName": self._audio_content,
                    }}})
                    await send({"event": {"promptEnd": {"promptName": self._prompt_name}}})
                    await send({"event": {"sessionEnd": {}}})
                    await stream.input_stream.close()
                except Exception:
                    pass

        # --- Receive Nova Sonic output ---
        async def _receive_output() -> None:
            try:
                while self._active:
                    try:
                        output = await stream.await_output()
                        result = await output[1].receive()
                        if not (result.value and result.value.bytes_):
                            continue
                        data = json.loads(result.value.bytes_.decode("utf-8"))
                        event = data.get("event", {})

                        if "audioOutput" in event:
                            b64 = event["audioOutput"].get("content", "")
                            if b64:
                                await websocket.send_bytes(base64.b64decode(b64))

                        elif "textOutput" in event:
                            # Log transcript for debugging only
                            logger.debug(
                                "Nova Sonic [%s]: %s",
                                event["textOutput"].get("role", ""),
                                event["textOutput"].get("content", ""),
                            )

                        elif "toolUse" in event:
                            # Accumulate tool call info
                            self._tool_name = event["toolUse"].get("toolName", "")
                            self._tool_use_id = event["toolUse"].get("toolUseId", "")
                            self._tool_content = event["toolUse"].get("content", "")
                            logger.info("Nova Sonic tool call: %s (id=%s)", self._tool_name, self._tool_use_id)

                        elif "contentEnd" in event:
                            content_end = event["contentEnd"]
                            if content_end.get("type") == "TOOL" and self._tool_use_id:
                                # Model finished describing the tool call — execute it
                                asyncio.create_task(_execute_tool(
                                    self._tool_name, self._tool_use_id, self._tool_content
                                ))
                                self._tool_name = ""
                                self._tool_use_id = ""
                                self._tool_content = ""

                    except StopAsyncIteration:
                        break
                    except Exception as exc:
                        logger.error("Output receive error: %s (%s)", exc, type(exc).__name__)
                        break
            finally:
                self._active = False

        await asyncio.gather(_receive_mic(), _receive_output(), return_exceptions=True)
        logger.info("Voice session ended")
