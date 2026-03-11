import { useState, useEffect, useCallback, useRef } from 'react'
import { Play, RefreshCw, Database, Monitor, ShoppingCart, Activity } from 'lucide-react'
import axios from 'axios'
import ComplianceScore from '../components/ComplianceScore.jsx'
import ScanStatus from '../components/ScanStatus.jsx'
import SentinelSplash from '../components/SentinelSplash.jsx'
import AudioBriefing from '../components/AudioBriefing.jsx'
import ScoreTrendChart from '../components/ScoreTrendChart.jsx'
import { useVoiceAssistant } from '../App.jsx'

const TOOLS = [
  { name: 'hr-portal', label: 'HRMS v3.1', icon: Database, desc: 'AcmeCorp HR (PeopleSoft-style)' },
  { name: 'it-admin', label: 'IT Admin v2.4', icon: Monitor, desc: 'IT Console (ServiceNow-style)' },
  { name: 'procurement', label: 'Procurement v1.8', icon: ShoppingCart, desc: 'Procurement Portal (SAP-style)' },
]

const SEVERITY_STYLES = {
  CRITICAL: { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400', dot: 'bg-red-500' },
  HIGH:     { bg: 'bg-orange-500/10', border: 'border-orange-500/30', text: 'text-orange-400', dot: 'bg-orange-500' },
  MEDIUM:   { bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', text: 'text-yellow-400', dot: 'bg-yellow-500' },
}

const EVENT_LABELS = {
  scan_started: 'Scan Started',
  scan_completed: 'Scan Completed',
  violation_detected: 'Violation Detected',
  remediation_approved: 'Remediation',
  violation_dismissed: 'Dismissed',
}

export default function Dashboard() {
  const [score, setScore] = useState(null)
  const [scoreData, setScoreData] = useState(null)
  const [violations, setViolations] = useState([])
  const [auditTrail, setAuditTrail] = useState([])
  const [scoreHistory, setScoreHistory] = useState([])
  const [scanning, setScanning] = useState(false)
  const [scanId, setScanId] = useState(null)
  const [loading, setLoading] = useState(true)

  // Splash state
  const alreadyLaunched = sessionStorage.getItem('sentinel_launched') === '1'
  const [splashDone, setSplashDone] = useState(alreadyLaunched)
  const [showBriefing, setShowBriefing] = useState(false)
  const [briefingScanId, setBriefingScanId] = useState(null)

  const { isVoiceActive, setIsVoiceActive, setAudioCtx, setMicStream, onActionRef } = useVoiceAssistant()

  const fetchData = useCallback(async () => {
    try {
      const [scoreRes, violationsRes, auditRes, historyRes] = await Promise.all([
        axios.get('/api/compliance-score'),
        axios.get('/api/violations'),
        axios.get('/api/audit-trail'),
        axios.get('/api/compliance-score/history'),
      ])
      setScore(scoreRes.data.score)
      setScoreData(scoreRes.data)
      setViolations(violationsRes.data)
      setAuditTrail(auditRes.data.slice(0, 10))
      setScoreHistory(historyRes.data)
    } catch (err) {
      console.error('Failed to fetch data:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const handleTriggerScan = async () => {
    try {
      setScanning(true)
      const { data } = await axios.post('/api/scan/trigger')
      setScanId(data.scan_id)
      setShowBriefing(false)
    } catch (err) {
      console.error('Scan trigger failed:', err)
      setScanning(false)
    }
  }

  const handleScanComplete = useCallback((scanResult) => {
    setScanning(false)
    const completedId = scanId
    setScanId(null)
    fetchData()

    // Always show the text briefing; mute its audio when Nova Sonic is active
    if (completedId) {
      setBriefingScanId(completedId)
      setShowBriefing(true)
    }
  }, [scanId, fetchData])

  // Voice assistant action handler — registered in context so it fires even when
  // the user has navigated away from Dashboard
  const handleVoiceAction = useCallback((action, params) => {
    if (action === 'scan_started' && params.scan_id) {
      setScanning(true)
      setScanId(params.scan_id)
      setShowBriefing(false)
    }
  }, [])

  // Keep the context ref up to date whenever the callback identity changes
  useEffect(() => {
    onActionRef.current = handleVoiceAction
  }, [handleVoiceAction, onActionRef])

  // Splash completion — AudioContext + mic stream created in button click handler
  const handleSplashReady = useCallback(({ audioCtx: ctx, micStream: stream }) => {
    setAudioCtx(ctx)
    setMicStream(stream)
    setSplashDone(true)
    setIsVoiceActive(true)
  }, [setAudioCtx, setMicStream, setIsVoiceActive])

  const bySeverity = scoreData?.by_severity || { CRITICAL: 0, HIGH: 0, MEDIUM: 0 }
  const openViolations = violations.filter(v => v.status === 'open')

  return (
    <>
      {/* Splash — only on first visit this session */}
      {!splashDone && (
        <SentinelSplash onReady={handleSplashReady} />
      )}

      <div className="p-8 max-w-7xl mx-auto pb-28">
        {/* Page header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">Compliance Dashboard</h1>
            <p className="text-slate-400 text-sm mt-1">Real-time SOC2 / HIPAA / GDPR monitoring</p>
          </div>
          <button
            onClick={handleTriggerScan}
            disabled={scanning}
            className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl font-medium text-sm transition-colors"
          >
            {scanning ? <RefreshCw size={16} className="animate-spin" /> : <Play size={16} />}
            {scanning ? 'Scanning...' : 'Run Scan'}
          </button>
        </div>

        {/* Live scan progress */}
        {scanning && scanId && (
          <ScanStatus scanId={scanId} onComplete={handleScanComplete} />
        )}

        {/* Text briefing — always shown after a scan; audio muted when Nova Sonic is active */}
        {showBriefing && briefingScanId && (
          <AudioBriefing
            scanId={briefingScanId}
            onDismiss={() => setShowBriefing(false)}
            initialMuted={isVoiceActive}
          />
        )}

        {/* Top row: score + severity cards */}
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 mt-6">
          <div className="lg:col-span-1 bg-slate-900 border border-slate-700 rounded-2xl p-6 flex flex-col items-center">
            <h2 className="text-slate-400 text-xs uppercase tracking-widest font-medium mb-4">Compliance Score</h2>
            <ComplianceScore score={score ?? 0} loading={loading} />
            <p className="text-slate-500 text-xs mt-3 text-center">
              {openViolations.length} open violation{openViolations.length !== 1 ? 's' : ''}
            </p>
          </div>

          <div className="lg:col-span-3 grid grid-cols-3 gap-4">
            {Object.entries(bySeverity).map(([sev, count]) => {
              const styles = SEVERITY_STYLES[sev] || SEVERITY_STYLES.MEDIUM
              return (
                <div key={sev} className={`${styles.bg} border ${styles.border} rounded-2xl p-5`}>
                  <div className={`w-2.5 h-2.5 rounded-full ${styles.dot} mb-3`} />
                  <p className={`text-3xl font-bold ${styles.text}`}>{count}</p>
                  <p className="text-slate-400 text-sm mt-1 font-medium">{sev}</p>
                  <p className="text-slate-500 text-xs mt-0.5">violations</p>
                </div>
              )
            })}

            <div className="col-span-3 bg-slate-900 border border-slate-700 rounded-2xl p-5">
              <h3 className="text-xs text-slate-400 uppercase tracking-widest font-medium mb-4">Tool Monitoring Status</h3>
              <div className="grid grid-cols-3 gap-4">
                {TOOLS.map(({ name, label, icon: Icon, desc }) => {
                  const toolViolations = violations.filter(v => v.tool_name === name && v.status === 'open')
                  return (
                    <div key={name} className="flex items-start gap-3">
                      <div className="p-2 bg-slate-800 rounded-lg">
                        <Icon size={16} className="text-blue-400" />
                      </div>
                      <div>
                        <p className="text-white text-sm font-medium">{label}</p>
                        <p className="text-slate-500 text-xs">{desc}</p>
                        <p className={`text-xs mt-1 font-medium ${toolViolations.length > 0 ? 'text-orange-400' : 'text-green-400'}`}>
                          {toolViolations.length > 0
                            ? `${toolViolations.length} open violation${toolViolations.length !== 1 ? 's' : ''}`
                            : 'No violations'
                          }
                        </p>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>

        {/* Score trend chart */}
        <div className="mt-6 bg-slate-900 border border-slate-700 rounded-2xl p-6">
          <div className="flex items-center gap-2 mb-2">
            <Activity size={16} className="text-blue-400" />
            <h2 className="text-white font-semibold">Compliance Score Trend</h2>
            <span className="text-slate-500 text-xs ml-1">— this session</span>
          </div>
          <ScoreTrendChart data={scoreHistory} />
        </div>

        {/* Recent audit activity */}
        <div className="mt-6 bg-slate-900 border border-slate-700 rounded-2xl">
          <div className="px-6 py-4 border-b border-slate-700 flex items-center gap-2">
            <Activity size={16} className="text-blue-400" />
            <h2 className="text-white font-semibold">Recent Activity</h2>
          </div>
          <div className="divide-y divide-slate-800">
            {auditTrail.length === 0 ? (
              <p className="px-6 py-8 text-slate-500 text-sm text-center">No activity yet. Trigger a scan to get started.</p>
            ) : (
              auditTrail.map((entry) => (
                <div key={entry.entry_id} className="px-6 py-3 flex items-start gap-4">
                  <div className={`mt-0.5 flex-shrink-0 w-2 h-2 rounded-full ${
                    entry.result === 'success' || entry.result === 'started'
                      ? 'bg-green-400'
                      : entry.result === 'failed'
                      ? 'bg-red-400'
                      : 'bg-slate-500'
                  }`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white truncate">{entry.action}</p>
                    <p className="text-xs text-slate-500 mt-0.5">
                      {new Date(entry.timestamp).toLocaleString()}
                      {entry.actor && ` · ${entry.actor}`}
                    </p>
                  </div>
                  <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded shrink-0">
                    {EVENT_LABELS[entry.event_type] || entry.event_type}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </>
  )
}
