import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { Mic, MicOff, X, Shield } from 'lucide-react'

const OUTPUT_SAMPLE_RATE = 24000 // Nova Sonic outputs 24kHz
const INPUT_SAMPLE_RATE = 16000  // Nova Sonic expects 16kHz

// Convert Float32 mic samples to 16-bit PCM bytes
function float32ToPcm16(float32Array) {
  const buf = new ArrayBuffer(float32Array.length * 2)
  const view = new DataView(buf)
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]))
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return new Uint8Array(buf)
}

// Convert 16-bit PCM bytes to Float32 for Web Audio playback
function pcm16ToFloat32(bytes) {
  const view = new DataView(bytes.buffer || bytes)
  const float32 = new Float32Array(bytes.byteLength / 2)
  for (let i = 0; i < float32.length; i++) {
    float32[i] = view.getInt16(i * 2, true) / 32768.0
  }
  return float32
}

const VoiceAssistant = memo(function VoiceAssistant({ audioCtx, micStream, onAction, onClose }) {
  const [state, setState] = useState('connecting') // connecting|idle|listening|speaking|error
  const [muted, setMuted] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [history, setHistory] = useState([])

  const wsRef = useRef(null)
  const processorRef = useRef(null)
  const sourceRef = useRef(null)
  const canvasRef = useRef(null)
  const analyserRef = useRef(null)
  const rafRef = useRef(null)
  const playbackCtxRef = useRef(null)
  const nextPlayTimeRef = useRef(0)
  const mutedRef = useRef(false)

  mutedRef.current = muted

  // Set up playback AudioContext at 24kHz
  useEffect(() => {
    try {
      playbackCtxRef.current = audioCtx || new AudioContext({ sampleRate: OUTPUT_SAMPLE_RATE })
      nextPlayTimeRef.current = playbackCtxRef.current.currentTime
    } catch {
      playbackCtxRef.current = null
    }
  }, [audioCtx])

  // Queue received PCM for seamless playback
  const playPcmChunk = useCallback((arrayBuffer) => {
    const ctx = playbackCtxRef.current
    if (!ctx) return

    const pcmBytes = new Uint8Array(arrayBuffer)
    if (pcmBytes.length < 2) return

    const float32 = pcm16ToFloat32(pcmBytes)
    const buffer = ctx.createBuffer(1, float32.length, OUTPUT_SAMPLE_RATE)
    buffer.copyToChannel(float32, 0)

    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.connect(ctx.destination)

    const startTime = Math.max(ctx.currentTime, nextPlayTimeRef.current)
    source.start(startTime)
    nextPlayTimeRef.current = startTime + buffer.duration
    setState('speaking')
    source.onended = () => {
      if (nextPlayTimeRef.current <= ctx.currentTime + 0.05) {
        setState('listening')
      }
    }
  }, [])

  // Connect WebSocket
  useEffect(() => {
    const ws = new WebSocket(`ws://${window.location.host}/api/voice-session`)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => setState('idle')
    ws.onclose = () => setState('error')
    ws.onerror = () => setState('error')

    ws.onmessage = (evt) => {
      if (evt.data instanceof ArrayBuffer) {
        // Binary = PCM audio from Nova Sonic
        playPcmChunk(evt.data)
      } else {
        // Text = JSON control message
        try {
          const msg = JSON.parse(evt.data)
          if (msg.type === 'action') {
            onAction?.(msg.action, msg)
          }
        } catch {
          // ignore
        }
      }
    }

    return () => { ws.close(); wsRef.current = null }
  }, [playPcmChunk, onAction])

  // Set up mic capture → PCM → WebSocket
  useEffect(() => {
    if (!micStream || !wsRef.current) return

    let micCtx
    try {
      micCtx = new AudioContext({ sampleRate: INPUT_SAMPLE_RATE })
    } catch {
      return
    }

    const source = micCtx.createMediaStreamSource(micStream)
    sourceRef.current = source

    // Analyser for waveform
    const analyser = micCtx.createAnalyser()
    analyser.fftSize = 256
    analyserRef.current = analyser
    source.connect(analyser)

    // ScriptProcessor for PCM capture (widely supported fallback to AudioWorklet)
    const processor = micCtx.createScriptProcessor(4096, 1, 1)
    processorRef.current = processor
    source.connect(processor)
    processor.connect(micCtx.destination)

    processor.onaudioprocess = (evt) => {
      if (mutedRef.current) return
      const ws = wsRef.current
      if (!ws || ws.readyState !== WebSocket.OPEN) return
      const float32 = evt.inputBuffer.getChannelData(0)
      const pcm = float32ToPcm16(float32)
      ws.send(pcm.buffer)
      setState('listening')
    }

    return () => {
      processor.disconnect()
      source.disconnect()
      micCtx.close()
    }
  }, [micStream])

  // Waveform canvas animation
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const draw = () => {
      rafRef.current = requestAnimationFrame(draw)
      const ctx = canvas.getContext('2d')
      const w = canvas.width
      const h = canvas.height
      ctx.clearRect(0, 0, w, h)

      const analyser = analyserRef.current
      const barCount = 24
      const barW = Math.floor(w / barCount) - 1

      if (analyser && state === 'listening' && !muted) {
        const data = new Uint8Array(analyser.frequencyBinCount)
        analyser.getByteFrequencyData(data)
        for (let i = 0; i < barCount; i++) {
          const val = (data[Math.floor(i * data.length / barCount)] / 255)
          const barH = Math.max(3, val * h * 0.85)
          ctx.fillStyle = `rgba(34,197,94,${0.6 + val * 0.4})`
          ctx.beginPath()
          ctx.roundRect(i * (barW + 1), (h - barH) / 2, barW, barH, 2)
          ctx.fill()
        }
      } else if (state === 'speaking') {
        // Synthetic waveform for Sentinel speaking
        const t = Date.now() / 300
        for (let i = 0; i < barCount; i++) {
          const val = 0.3 + 0.5 * Math.abs(Math.sin(t + i * 0.4)) * Math.abs(Math.sin(t * 0.7 + i * 0.2))
          const barH = Math.max(3, val * h * 0.85)
          ctx.fillStyle = `rgba(96,165,250,${0.6 + val * 0.4})`
          ctx.beginPath()
          ctx.roundRect(i * (barW + 1), (h - barH) / 2, barW, barH, 2)
          ctx.fill()
        }
      } else {
        // Idle — flat low bars
        for (let i = 0; i < barCount; i++) {
          ctx.fillStyle = 'rgba(100,116,139,0.4)'
          ctx.beginPath()
          ctx.roundRect(i * (barW + 1), h / 2 - 2, barW, 4, 2)
          ctx.fill()
        }
      }
    }

    draw()
    return () => cancelAnimationFrame(rafRef.current)
  }, [state, muted])

  // Inject scan result context into the voice session
  const injectContext = useCallback((text) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'inject_context', text }))
    }
  }, [])

  const stateLabel = {
    connecting: 'Connecting...',
    idle: 'Ready',
    listening: 'Listening...',
    speaking: 'Sentinel speaking',
    error: 'Connection error',
  }[state] || state

  const stateColor = {
    connecting: 'text-slate-400',
    idle: 'text-slate-400',
    listening: 'text-green-400',
    speaking: 'text-blue-400',
    error: 'text-red-400',
  }[state] || 'text-slate-400'

  return (
    <div
      className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-40 transition-all duration-300 ${
        expanded ? 'w-[520px]' : 'w-[380px]'
      }`}
    >
      <div
        className="bg-slate-900/95 border border-slate-700 rounded-2xl shadow-2xl overflow-hidden backdrop-blur-sm"
        style={{ boxShadow: '0 0 40px rgba(37,99,235,0.15), 0 8px 32px rgba(0,0,0,0.5)' }}
      >
        {/* Main bar */}
        <div
          className="flex items-center gap-3 px-4 py-3 cursor-pointer select-none"
          onClick={() => setExpanded(e => !e)}
        >
          {/* Shield / status dot */}
          <div className="relative flex-shrink-0">
            <Shield size={20} className="text-blue-400" />
            <span
              className={`absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full ${
                state === 'listening' ? 'bg-green-400 animate-pulse' :
                state === 'speaking' ? 'bg-blue-400 animate-pulse' :
                state === 'error' ? 'bg-red-400' : 'bg-slate-500'
              }`}
            />
          </div>

          {/* Waveform */}
          <canvas ref={canvasRef} width={120} height={32} className="flex-shrink-0" />

          {/* Status / transcript */}
          <div className="flex-1 min-w-0">
            <p className={`text-xs font-medium ${stateColor}`}>{stateLabel}</p>
            {transcript && (
              <p className="text-xs text-slate-400 truncate mt-0.5">{transcript}</p>
            )}
          </div>

          {/* Controls */}
          <div className="flex items-center gap-2 flex-shrink-0" onClick={e => e.stopPropagation()}>
            <button
              onClick={() => setMuted(m => !m)}
              className={`p-1.5 rounded-lg transition-colors ${muted ? 'bg-red-500/20 text-red-400' : 'text-slate-400 hover:text-white hover:bg-slate-800'}`}
              title={muted ? 'Unmute' : 'Mute'}
            >
              {muted ? <MicOff size={14} /> : <Mic size={14} />}
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
              title="Close voice assistant"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* Expanded conversation history */}
        {expanded && history.length > 0 && (
          <div className="border-t border-slate-800 px-4 py-3 max-h-48 overflow-y-auto space-y-2">
            {history.map((entry, i) => (
              <div key={i} className={`text-xs ${entry.role === 'user' ? 'text-green-400' : 'text-blue-300'}`}>
                <span className="font-semibold">{entry.role === 'user' ? 'You' : 'Sentinel'}: </span>
                {entry.text}
              </div>
            ))}
          </div>
        )}

        {/* No mic warning */}
        {!micStream && state !== 'connecting' && (
          <div className="border-t border-slate-800 px-4 py-2 text-xs text-amber-400 text-center">
            Microphone not available — listening to Sentinel only
          </div>
        )}
      </div>
    </div>
  )
})

export default VoiceAssistant
