import { useEffect, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import axios from 'axios'
import AgentActivityFeed from './AgentActivityFeed.jsx'

export default function ScanStatus({ scanId, onComplete }) {
  const [useFallback, setUseFallback] = useState(false)
  const intervalRef = useRef(null)

  // Polling fallback — only activates if SSE connection fails
  useEffect(() => {
    if (!scanId || !useFallback) return

    const poll = async () => {
      try {
        const { data } = await axios.get(`/api/scan/${scanId}/status`)
        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(intervalRef.current)
          if (onComplete) onComplete(data)
        }
      } catch (err) {
        console.error('Polling error:', err)
      }
    }

    poll()
    intervalRef.current = setInterval(poll, 3000)
    return () => clearInterval(intervalRef.current)
  }, [scanId, useFallback])

  if (!scanId) return null

  // SSE feed — if it signals an error, switch to polling fallback
  if (!useFallback) {
    return (
      <AgentActivityFeed
        scanId={scanId}
        onComplete={onComplete}
        onError={() => setUseFallback(true)}
      />
    )
  }

  // Polling fallback UI (original spinner)
  return (
    <div className="mt-4 p-4 bg-slate-800 border border-slate-700 rounded-lg">
      <div className="flex items-center gap-3">
        <Loader2 size={18} className="text-blue-400 animate-spin" />
        <div>
          <p className="text-sm font-medium text-white">Scan in progress</p>
          <p className="text-xs text-slate-400 mt-0.5">
            Nova Act is scanning all three legacy tools in parallel...
          </p>
        </div>
      </div>
      <div className="mt-3 space-y-1.5">
        {['hr-portal', 'it-admin', 'procurement'].map((tool) => (
          <div key={tool} className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
            <span className="text-xs text-slate-400">Scanning {tool}...</span>
          </div>
        ))}
      </div>
      <div className="mt-3 h-1 bg-slate-700 rounded-full overflow-hidden">
        <div className="h-full bg-blue-500 rounded-full"
          style={{ width: '60%', animation: 'pulse 1.5s ease-in-out infinite' }} />
      </div>
    </div>
  )
}
