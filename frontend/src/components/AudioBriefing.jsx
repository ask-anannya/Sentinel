import { useEffect, useRef, useState } from 'react'
import { Volume2, VolumeX, RotateCcw, X } from 'lucide-react'
import axios from 'axios'

export default function AudioBriefing({ scanId, onDismiss, initialMuted = false }) {
  const [text, setText] = useState('')
  const [displayedText, setDisplayedText] = useState('')
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(initialMuted)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const audioRef = useRef(null)
  const blobUrlRef = useRef(null)
  const typewriterRef = useRef(null)

  const startTypewriter = (fullText) => {
    clearInterval(typewriterRef.current)
    setDisplayedText('')
    let i = 0
    typewriterRef.current = setInterval(() => {
      i++
      setDisplayedText(fullText.slice(0, i))
      if (i >= fullText.length) clearInterval(typewriterRef.current)
    }, 35)
  }

  const playAudio = (url) => {
    const audio = new Audio(url)
    audioRef.current = audio
    audio.muted = muted

    audio.onplay = () => setPlaying(true)
    audio.onended = () => {
      setPlaying(false)
      setTimeout(onDismiss, 2000)
    }
    audio.onerror = () => setPlaying(false)
    audio.play().catch(() => setPlaying(false))
  }

  useEffect(() => {
    if (!scanId) return

    let cancelled = false

    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        // Fetch text and audio in parallel — briefing_generator caches the text
        // so both calls share the same LLM result
        const [textRes, audioRes] = await Promise.all([
          axios.get(`/api/scan/${scanId}/briefing-text`),
          fetch(`/api/scan/${scanId}/briefing-audio`),
        ])

        if (cancelled) return

        const briefingText = textRes.data.text
        setText(briefingText)
        startTypewriter(briefingText)

        const audioBlob = await audioRes.blob()
        if (cancelled) return

        const url = URL.createObjectURL(audioBlob)
        blobUrlRef.current = url
        playAudio(url)
      } catch (err) {
        if (!cancelled) {
          setError('Audio briefing unavailable')
          setLoading(false)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()

    return () => {
      cancelled = true
      clearInterval(typewriterRef.current)
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current = null
      }
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current)
        blobUrlRef.current = null
      }
    }
  }, [scanId])

  const handleMuteToggle = () => {
    setMuted(m => {
      if (audioRef.current) audioRef.current.muted = !m
      return !m
    })
  }

  const handleReplay = () => {
    if (blobUrlRef.current) {
      startTypewriter(text)
      playAudio(blobUrlRef.current)
    }
  }

  return (
    <div
      className="mt-4 rounded-2xl p-px overflow-hidden"
      style={{ background: 'linear-gradient(135deg, #2563eb 0%, #7c3aed 50%, #2563eb 100%)' }}
    >
      <div className="bg-slate-900 rounded-2xl px-5 py-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className={`relative ${playing ? 'animate-pulse' : ''}`}>
              <Volume2 size={16} className="text-blue-400" />
              {playing && (
                <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-blue-400 animate-ping" />
              )}
            </div>
            <span className="text-xs font-semibold text-white uppercase tracking-widest">
              Sentinel Briefing
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={handleMuteToggle}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
              title={muted ? 'Unmute' : 'Mute'}
            >
              {muted ? <VolumeX size={13} /> : <Volume2 size={13} />}
            </button>
            {!playing && text && (
              <button
                onClick={handleReplay}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                title="Replay"
              >
                <RotateCcw size={13} />
              </button>
            )}
            <button
              onClick={onDismiss}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            >
              <X size={13} />
            </button>
          </div>
        </div>

        {/* Waveform bars (visual only) */}
        {playing && (
          <div className="flex items-center gap-0.5 h-5 mb-3">
            {Array.from({ length: 20 }).map((_, i) => (
              <div
                key={i}
                className="flex-1 rounded-full bg-blue-400"
                style={{
                  height: `${20 + 60 * Math.abs(Math.sin(Date.now() / 200 + i * 0.5))}%`,
                  animation: `pulse ${0.6 + (i % 4) * 0.15}s ease-in-out infinite`,
                  animationDelay: `${i * 0.05}s`,
                }}
              />
            ))}
          </div>
        )}

        {/* Briefing text */}
        <div className="min-h-[2.5rem]">
          {loading && !displayedText && (
            <p className="text-slate-500 text-sm italic">Generating briefing...</p>
          )}
          {error && (
            <p className="text-red-400 text-sm">{error}</p>
          )}
          {displayedText && (
            <p className="text-slate-200 text-sm leading-relaxed">
              {displayedText}
              {displayedText.length < text.length && (
                <span className="animate-pulse text-blue-400">|</span>
              )}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
