"""
Text-to-speech via Amazon Nova Sonic bidirectional streaming.
Uses aws-sdk-bedrock-runtime (Smithy-based SDK) which supports HTTP/2 bidirectional streams
— boto3 does not support this operation.

Returns WAV bytes (24kHz, 16-bit, mono) ready to serve as audio/wav.
Call synthesize_speech() from async code via run_in_executor (it wraps asyncio.run).
"""

import asyncio
import base64
import io
import json
import logging
import os
import struct
import uuid
import wave

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

logger = logging.getLogger(__name__)

NOVA_SONIC_MODEL_ID = "amazon.nova-2-sonic-v1:0"
INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000


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


def _silence_frames(duration_ms: int = 500) -> bytes:
    num_samples = int(INPUT_SAMPLE_RATE * duration_ms / 1000)
    return struct.pack(f"<{num_samples}h", *([0] * num_samples))


async def _synthesize_async(text: str, voice_id: str) -> bytes:
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    client = _make_client(region)

    prompt_name = str(uuid.uuid4())
    system_content = str(uuid.uuid4())
    user_content = str(uuid.uuid4())
    audio_content = str(uuid.uuid4())

    stream = await client.invoke_model_with_bidirectional_stream(
        InvokeModelWithBidirectionalStreamOperationInput(model_id=NOVA_SONIC_MODEL_ID)
    )

    async def send(payload: dict) -> None:
        event = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=json.dumps(payload).encode("utf-8"))
        )
        await stream.input_stream.send(event)

    # Session start
    await send({"event": {"sessionStart": {
        "inferenceConfiguration": {"maxTokens": 1024, "topP": 0.95, "temperature": 0.7}
    }}})

    # Prompt start — declares voice + output formats
    await send({"event": {"promptStart": {
        "promptName": prompt_name,
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
    }}})

    # System prompt
    await send({"event": {"contentStart": {
        "promptName": prompt_name, "contentName": system_content,
        "type": "TEXT", "interactive": False, "role": "SYSTEM",
        "textInputConfiguration": {"mediaType": "text/plain"},
    }}})
    await send({"event": {"textInput": {
        "promptName": prompt_name, "contentName": system_content,
        "content": (
            "You are Sentinel, an autonomous compliance monitoring assistant. "
            "Speak naturally and professionally. Keep responses concise."
        ),
    }}})
    await send({"event": {"contentEnd": {"promptName": prompt_name, "contentName": system_content}}})

    # Text to synthesize (user turn)
    await send({"event": {"contentStart": {
        "promptName": prompt_name, "contentName": user_content,
        "type": "TEXT", "interactive": False, "role": "USER",
        "textInputConfiguration": {"mediaType": "text/plain"},
    }}})
    await send({"event": {"textInput": {
        "promptName": prompt_name, "contentName": user_content, "content": text,
    }}})
    await send({"event": {"contentEnd": {"promptName": prompt_name, "contentName": user_content}}})

    # Silent audio input — required to trigger Nova Sonic to respond
    silence_b64 = base64.b64encode(_silence_frames(500)).decode()
    await send({"event": {"contentStart": {
        "promptName": prompt_name, "contentName": audio_content,
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
    await send({"event": {"audioInput": {
        "promptName": prompt_name, "contentName": audio_content, "content": silence_b64,
    }}})
    await send({"event": {"contentEnd": {"promptName": prompt_name, "contentName": audio_content}}})

    # Close prompt + session
    await send({"event": {"promptEnd": {"promptName": prompt_name}}})
    await send({"event": {"sessionEnd": {}}})
    await stream.input_stream.close()

    # Collect audio output
    pcm_chunks: list[bytes] = []
    while True:
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
                    pcm_chunks.append(base64.b64decode(b64))
            elif "completionEnd" in event:
                break
        except StopAsyncIteration:
            break
        except Exception as exc:
            logger.error("Nova Sonic output error: %s", exc)
            break

    if not pcm_chunks:
        raise RuntimeError("Nova Sonic returned no audio output")

    pcm_data = b"".join(pcm_chunks)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(OUTPUT_SAMPLE_RATE)
        wf.writeframes(pcm_data)

    logger.info("Nova Sonic TTS: %.1fs audio", len(pcm_data) / (OUTPUT_SAMPLE_RATE * 2))
    return buf.getvalue()


def synthesize_speech(text: str, voice_id: str = "matthew") -> bytes:
    """
    Synchronous wrapper — call from async code via run_in_executor.
    Returns WAV bytes (24kHz, 16-bit, mono).
    """
    return asyncio.run(_synthesize_async(text, voice_id))
