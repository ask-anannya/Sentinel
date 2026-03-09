import { useEffect, useState } from 'react'
import { Shield } from 'lucide-react'

const TAGLINE = 'SENTINEL'
const SUBTITLE = 'Autonomous Compliance Assistant'

export default function SentinelSplash({ onReady }) {
  const [shieldVisible, setShieldVisible] = useState(false)
  const [typedChars, setTypedChars] = useState(0)
  const [subtitleVisible, setSubtitleVisible] = useState(false)
  const [buttonVisible, setButtonVisible] = useState(false)
  const [exiting, setExiting] = useState(false)

  useEffect(() => {
    // Staggered animation sequence
    const t1 = setTimeout(() => setShieldVisible(true), 300)
    const t2 = setTimeout(() => {
      let i = 0
      const interval = setInterval(() => {
        i++
        setTypedChars(i)
        if (i >= TAGLINE.length) clearInterval(interval)
      }, 80)
    }, 900)
    const t3 = setTimeout(() => setSubtitleVisible(true), 1700)
    const t4 = setTimeout(() => setButtonVisible(true), 2400)

    return () => [t1, t2, t3, t4].forEach(clearTimeout)
  }, [])

  const handleFireUp = async () => {
    if (exiting) return
    setExiting(true)

    // Create & unlock AudioContext inside the click handler — satisfies browser autoplay policy
    let audioCtx = null
    try {
      audioCtx = new AudioContext()
      await audioCtx.resume()
    } catch {
      audioCtx = null
    }

    // Request mic permission in the same gesture
    let stream = null
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
    } catch {
      stream = null // mic denied — voice assistant will run in TTS-only mode
    }

    sessionStorage.setItem('sentinel_launched', '1')
    onReady({ audioCtx, micStream: stream })
  }

  return (
    <div
      className={`fixed inset-0 z-[100] flex flex-col items-center justify-center bg-slate-950 transition-opacity duration-700 ${
        exiting ? 'opacity-0 pointer-events-none' : 'opacity-100'
      }`}
    >
      {/* Particle ring */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        {Array.from({ length: 12 }).map((_, i) => (
          <div
            key={i}
            className="absolute w-1 h-1 rounded-full bg-blue-500/30"
            style={{
              top: `${50 + 30 * Math.sin((i / 12) * 2 * Math.PI)}%`,
              left: `${50 + 15 * Math.cos((i / 12) * 2 * Math.PI)}%`,
              animation: `ping ${1.5 + (i % 3) * 0.3}s ease-in-out infinite`,
              animationDelay: `${i * 0.12}s`,
              opacity: shieldVisible ? 1 : 0,
              transition: 'opacity 1s ease',
            }}
          />
        ))}
      </div>

      {/* Shield icon */}
      <div
        className="transition-all duration-700 ease-out mb-8"
        style={{
          transform: shieldVisible ? 'scale(1)' : 'scale(0)',
          opacity: shieldVisible ? 1 : 0,
        }}
      >
        <div
          className="relative p-6 rounded-full"
          style={{
            background: 'radial-gradient(circle, rgba(59,130,246,0.15) 0%, transparent 70%)',
            boxShadow: shieldVisible ? '0 0 60px rgba(59,130,246,0.4), 0 0 120px rgba(59,130,246,0.15)' : 'none',
            transition: 'box-shadow 1s ease',
          }}
        >
          <Shield size={72} className="text-blue-400" strokeWidth={1.5} />
        </div>
      </div>

      {/* Typewriter title */}
      <div className="h-14 flex items-center justify-center mb-3">
        <span
          className="font-mono font-bold tracking-[0.3em] text-white"
          style={{ fontSize: '2.5rem' }}
        >
          {TAGLINE.slice(0, typedChars)}
          {typedChars < TAGLINE.length && (
            <span className="animate-pulse text-blue-400">|</span>
          )}
        </span>
      </div>

      {/* Subtitle */}
      <p
        className="text-slate-400 text-sm tracking-widest uppercase mb-16 transition-all duration-700"
        style={{ opacity: subtitleVisible ? 1 : 0, transform: subtitleVisible ? 'translateY(0)' : 'translateY(8px)' }}
      >
        {SUBTITLE}
      </p>

      {/* Fire up button */}
      <div
        className="transition-all duration-500"
        style={{ opacity: buttonVisible ? 1 : 0, transform: buttonVisible ? 'translateY(0) scale(1)' : 'translateY(12px) scale(0.95)' }}
      >
        <button
          onClick={handleFireUp}
          className="relative px-10 py-3.5 rounded-2xl text-white font-semibold text-sm tracking-wide overflow-hidden group"
          style={{
            background: 'linear-gradient(135deg, #2563eb 0%, #7c3aed 100%)',
            boxShadow: '0 0 30px rgba(37,99,235,0.5), 0 4px 20px rgba(0,0,0,0.4)',
          }}
        >
          {/* Animated shimmer */}
          <span
            className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300"
            style={{ background: 'linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%)' }}
          />
          <span className="relative flex items-center gap-2">
            <Shield size={16} />
            Fire up Sentinel
          </span>
        </button>
        <p className="text-slate-600 text-xs text-center mt-3">
          Microphone access may be requested
        </p>
      </div>
    </div>
  )
}
