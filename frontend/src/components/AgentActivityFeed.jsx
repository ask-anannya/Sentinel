import { useEffect, useRef, useState } from 'react'

const TOOLS = ['hr-portal', 'it-admin', 'procurement']

const TOOL_LABELS = {
  'hr-portal': 'HR Portal',
  'it-admin': 'IT Admin',
  'procurement': 'Procurement',
}

const STATUS_ICON = {
  running: '⏳',
  success: '✅',
  error: '❌',
}

const STATUS_COLOR = {
  running: 'text-blue-400',
  success: 'text-green-400',
  error: 'text-red-400',
}

function Lightbox({ src, onClose }) {
  // Close on backdrop click or Escape key
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ background: 'rgba(0,0,0,0.88)' }}
      onClick={onClose}
    >
      <img
        src={src}
        alt="Agent view"
        className="max-w-full max-h-full rounded-xl shadow-2xl border border-slate-700 object-contain"
        onClick={(e) => e.stopPropagation()}
      />
      <button
        onClick={onClose}
        className="absolute top-4 right-4 text-slate-400 hover:text-white text-2xl leading-none"
      >
        ✕
      </button>
    </div>
  )
}

export default function AgentActivityFeed({ scanId, onComplete, onError }) {
  const [events, setEvents] = useState({ 'hr-portal': [], 'it-admin': [], 'procurement': [] })
  const [toolStatus, setToolStatus] = useState({ 'hr-portal': 'running', 'it-admin': 'running', 'procurement': 'running' })
  const [scanComplete, setScanComplete] = useState(false)
  const [lightboxImg, setLightboxImg] = useState(null)
  const columnRefs = useRef({})

  useEffect(() => {
    if (!scanId) return

    const es = new EventSource(`/api/scan/${scanId}/events`)

    es.onmessage = (e) => {
      let event
      try {
        event = JSON.parse(e.data)
      } catch {
        return
      }

      if (event.tool === 'system' && event.message === 'scan_complete') {
        setScanComplete(true)
        es.close()
        if (onComplete) onComplete()
        return
      }

      if (TOOLS.includes(event.tool)) {
        setEvents((prev) => ({
          ...prev,
          [event.tool]: [...prev[event.tool], event],
        }))

        if (event.status === 'error') {
          setToolStatus((prev) => ({ ...prev, [event.tool]: 'error' }))
        } else if (event.message.startsWith('Extraction complete')) {
          setToolStatus((prev) => ({ ...prev, [event.tool]: 'success' }))
        }
      }
    }

    es.onerror = () => {
      es.close()
      if (onError) onError()
    }

    return () => es.close()
  }, [scanId])

  // Auto-scroll each column to bottom as events arrive
  useEffect(() => {
    TOOLS.forEach((tool) => {
      const el = columnRefs.current[tool]
      if (el) el.scrollTop = el.scrollHeight
    })
  }, [events])

  return (
    <>
      {lightboxImg && (
        <Lightbox
          src={`/api/screenshots/${lightboxImg}`}
          onClose={() => setLightboxImg(null)}
        />
      )}

      <div className="mt-4 bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
        {/* Header */}
        <div className="px-4 py-3 border-b border-slate-700 flex items-center gap-2">
          <span className="text-xs font-mono text-slate-400 uppercase tracking-widest">
            {scanComplete ? 'Analysis complete — processing violations...' : 'Live Agent Activity'}
          </span>
          {!scanComplete && (
            <span className="ml-auto flex gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-ping" />
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-ping [animation-delay:0.2s]" />
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-ping [animation-delay:0.4s]" />
            </span>
          )}
        </div>

        {/* Three-column feed */}
        <div className="grid grid-cols-3 divide-x divide-slate-800">
          {TOOLS.map((tool, idx) => (
            <div key={tool} className="flex flex-col">
              {/* Column header */}
              <div className="px-3 py-2 border-b border-slate-800 flex items-center gap-2 bg-slate-800/50">
                <span className="text-sm">🤖</span>
                <span className="text-xs font-semibold text-white">{TOOL_LABELS[tool]}</span>
                <span className={`ml-auto text-xs ${STATUS_COLOR[toolStatus[tool]]}`}>
                  {STATUS_ICON[toolStatus[tool]]}
                </span>
              </div>

              {/* Event log — grows with content, scrollable once tall */}
              <div
                ref={(el) => { columnRefs.current[tool] = el }}
                className="overflow-y-auto max-h-[640px] p-2 space-y-1 font-mono text-[11px] bg-slate-950/40"
              >
                {events[tool].length === 0 ? (
                  <div className="text-slate-600 italic px-1 pt-1">Waiting for agent {idx + 1}...</div>
                ) : (
                  events[tool].map((ev, i) => (
                    <div key={i}>
                      {/* Event line */}
                      <div
                        className={`flex gap-2 items-start px-1 rounded ${
                          i === events[tool].length - 1 && !scanComplete
                            ? 'bg-slate-800/60 animate-pulse'
                            : ''
                        }`}
                      >
                        <span className="text-slate-600 shrink-0 tabular-nums">{ev.timestamp}</span>
                        <span className={STATUS_COLOR[ev.status]}>{ev.message}</span>
                      </div>

                      {/* Inline screenshot — full column width, click to expand */}
                      {ev.screenshot && (
                        <div className="mt-1.5 mb-1">
                          <img
                            src={`/api/screenshots/${ev.screenshot}`}
                            alt={ev.message}
                            className="w-full rounded-lg border border-slate-700 cursor-zoom-in object-cover hover:border-blue-500 transition-colors"
                            onClick={() => setLightboxImg(ev.screenshot)}
                          />
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
