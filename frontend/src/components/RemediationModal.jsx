import { useEffect, useRef, useState } from 'react'
import { X, Shield, CheckCircle, AlertCircle, Circle } from 'lucide-react'
import axios from 'axios'

const REMEDIATION_PREVIEWS = {
  ACCESS_VIOLATION: [
    'Navigate to user management page',
    'Log into portal',
    'Locate user by username',
    'Disable account',
    'Capture confirmation screenshot',
    'Update audit trail',
  ],
  INACTIVE_ADMIN: [
    'Navigate to user management page',
    'Log into portal',
    'Locate user by username',
    'Deactivate account',
    'Capture confirmation screenshot',
    'Update audit trail',
  ],
  PERMISSION_CREEP: [
    'Navigate to user management page',
    'Log into portal',
    'Locate user by username',
    'Revoke admin access',
    'Capture confirmation screenshot',
    'Update audit trail',
  ],
  SHARED_ACCOUNT: [
    'Flag account for manual security review',
    'Document the shared account violation',
    'Notify security team for organizational decision',
    'No autonomous action taken (SOC2 CC6.3 compliance)',
  ],
}

function StepIcon({ stepStatus }) {
  if (stepStatus === 'done') return <CheckCircle size={16} className="text-green-400 flex-shrink-0 mt-0.5" />
  if (stepStatus === 'running') return (
    <div className="w-4 h-4 flex-shrink-0 mt-0.5 rounded-full border-2 border-blue-400 border-t-transparent animate-spin" />
  )
  if (stepStatus === 'error') return <AlertCircle size={16} className="text-red-400 flex-shrink-0 mt-0.5" />
  return <Circle size={16} className="text-slate-600 flex-shrink-0 mt-0.5" />
}

function Lightbox({ src, onClose }) {
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-6"
      style={{ background: 'rgba(0,0,0,0.92)' }}
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

export default function RemediationModal({ violation, onClose, onComplete }) {
  const [approvedBy, setApprovedBy] = useState('')
  const [status, setStatus] = useState('idle')  // idle | executing | success | error
  const [result, setResult] = useState(null)
  const [stepStatuses, setStepStatuses] = useState([])
  const [activeStep, setActiveStep] = useState(-1)
  const [stepScreenshots, setStepScreenshots] = useState({})  // step_index -> filename
  const [lightboxImg, setLightboxImg] = useState(null)
  const [useFallback, setUseFallback] = useState(false)
  const esRef = useRef(null)

  if (!violation) return null

  const steps = REMEDIATION_PREVIEWS[violation.violation_type] || []
  const isShared = violation.violation_type === 'SHARED_ACCOUNT'

  const handleConfirm = async () => {
    if (!approvedBy.trim()) return

    setStepStatuses(steps.map(() => 'pending'))
    setActiveStep(-1)
    setStepScreenshots({})
    setStatus('executing')

    // Open SSE before POST so no early events are missed
    const es = new EventSource(`/api/violations/${violation.violation_id}/remediation-events`)
    esRef.current = es

    es.onmessage = (e) => {
      let event
      try { event = JSON.parse(e.data) } catch { return }

      const { tool, message, status: evStatus, step_index, screenshot } = event

      if (tool === 'system') {
        es.close()
        if (message === 'remediation_complete') {
          setStepStatuses(steps.map(() => 'done'))
          setActiveStep(steps.length)
          setStatus('success')
          setResult({ success: true })
          setTimeout(() => onComplete?.(), 2500)
        } else if (message === 'remediation_failed') {
          setStatus('error')
          setResult({ error: 'Remediation failed. Check audit trail for details.' })
        }
        return
      }

      if (step_index == null) return

      // Capture screenshot for this step if present
      if (screenshot) {
        setStepScreenshots((prev) => ({ ...prev, [step_index]: screenshot }))
      }

      if (evStatus === 'error') {
        setStepStatuses((prev) => {
          const next = [...prev]
          next[step_index] = 'error'
          return next
        })
        setActiveStep(step_index)
        return
      }

      if (evStatus === 'running') {
        setStepStatuses((prev) => {
          const next = [...prev]
          for (let i = 0; i < step_index; i++) next[i] = 'done'
          next[step_index] = 'running'
          return next
        })
        setActiveStep(step_index)
      } else if (evStatus === 'success') {
        setStepStatuses((prev) => {
          const next = [...prev]
          for (let i = 0; i <= step_index; i++) next[i] = 'done'
          return next
        })
        setActiveStep(step_index + 1)
      }
    }

    es.onerror = () => {
      es.close()
      setUseFallback(true)
    }

    try {
      await axios.post(
        `/api/violations/${violation.violation_id}/approve`,
        { approved_by: approvedBy.trim() }
      )
    } catch (err) {
      es.close()
      setStatus('error')
      setResult({ error: err.response?.data?.detail || err.message })
    }
  }

  useEffect(() => {
    return () => esRef.current?.close()
  }, [])

  const doneCount = stepStatuses.filter(s => s === 'done').length
  const progressPct = steps.length > 0 ? Math.round((doneCount / steps.length) * 100) : 0

  return (
    <>
      {lightboxImg && (
        <Lightbox
          src={`/api/screenshots/${lightboxImg}`}
          onClose={() => setLightboxImg(null)}
        />
      )}

      <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
           style={{ background: 'rgba(0,0,0,0.75)' }}>
        <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-lg shadow-2xl flex flex-col max-h-[90vh]">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700 flex-shrink-0">
            <div className="flex items-center gap-3">
              <Shield size={18} className="text-blue-400" />
              <h2 className="text-white font-semibold">
                {isShared ? 'Flag for Manual Review' : 'Approve Remediation'}
              </h2>
            </div>
            <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
              <X size={20} />
            </button>
          </div>

          {/* Body — scrollable */}
          <div className="px-6 py-5 space-y-5 overflow-y-auto flex-1">
            {/* Violation summary */}
            <div className="bg-slate-800 rounded-xl p-4">
              <p className="text-xs text-slate-400 uppercase tracking-wide font-medium mb-2">Violation</p>
              <p className="text-white font-medium">{violation.username} — {violation.violation_type}</p>
              <p className="text-slate-400 text-sm mt-1">{violation.tool_name} · {violation.severity}</p>
            </div>

            {/* Step list */}
            <div>
              <p className="text-xs text-slate-400 uppercase tracking-wide font-medium mb-3">
                {isShared ? 'Actions that will be taken:' : 'Nova Act will execute these steps:'}
              </p>

              {status === 'idle' ? (
                // Static numbered preview
                <ol className="space-y-2">
                  {steps.map((step, i) => (
                    <li key={i} className="flex items-start gap-2.5 text-sm">
                      <span className="flex-shrink-0 w-5 h-5 rounded-full bg-blue-600 text-white text-xs flex items-center justify-center font-bold mt-0.5">
                        {i + 1}
                      </span>
                      <span className="text-slate-300">{step}</span>
                    </li>
                  ))}
                </ol>
              ) : (
                // Live step tracker with inline screenshots
                <ol className="space-y-1">
                  {steps.map((step, i) => {
                    const st = stepStatuses[i] || 'pending'
                    const isActive = st === 'running'
                    const shot = stepScreenshots[i]

                    return (
                      <li key={i}>
                        {/* Step row */}
                        <div
                          className={`flex items-center gap-2.5 text-sm rounded-lg px-2 py-1.5 transition-colors ${
                            isActive ? 'bg-blue-500/10' : ''
                          }`}
                        >
                          <StepIcon stepStatus={st} />
                          <span className={
                            st === 'done' ? 'text-slate-400' :
                            st === 'running' ? 'text-white font-medium' :
                            st === 'error' ? 'text-red-400' :
                            'text-slate-500'
                          }>
                            {step}
                          </span>
                        </div>

                        {/* Inline screenshot — full modal width, click to expand */}
                        {shot && (
                          <div className="mt-1.5 mb-2 px-2">
                            <img
                              src={`/api/screenshots/${shot}`}
                              alt={`Step ${i + 1} — ${step}`}
                              className="w-full rounded-lg border border-slate-700 cursor-zoom-in hover:border-blue-500 transition-colors object-cover"
                              onClick={() => setLightboxImg(shot)}
                            />
                            <p className="text-[10px] text-slate-600 mt-1 text-center">
                              Click to expand
                            </p>
                          </div>
                        )}
                      </li>
                    )
                  })}
                </ol>
              )}
            </div>

            {/* Progress bar */}
            {status === 'executing' && !useFallback && steps.length > 0 && (
              <div>
                <div className="flex justify-between text-xs text-slate-500 mb-1.5">
                  <span>Step {Math.min(activeStep + 1, steps.length)} of {steps.length}</span>
                  <span>{progressPct}%</span>
                </div>
                <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full transition-all duration-500"
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
              </div>
            )}

            {/* Fallback spinner */}
            {status === 'executing' && useFallback && (
              <div className="flex items-center gap-3 p-4 bg-blue-500/10 border border-blue-500/30 rounded-xl">
                <div className="w-5 h-5 rounded-full border-2 border-blue-400 border-t-transparent animate-spin flex-shrink-0" />
                <div>
                  <p className="text-white text-sm font-medium">Nova Act is executing...</p>
                  <p className="text-slate-400 text-xs mt-0.5">Browser automation in progress. This may take 30–60 seconds.</p>
                </div>
              </div>
            )}

            {/* Success state */}
            {status === 'success' && (
              <div className="flex items-center gap-3 p-4 bg-green-500/10 border border-green-500/30 rounded-xl">
                <CheckCircle size={20} className="text-green-400 flex-shrink-0" />
                <div>
                  <p className="text-white text-sm font-medium">Remediation complete</p>
                  <p className="text-slate-400 text-xs mt-0.5">Violation resolved and audit trail updated.</p>
                </div>
              </div>
            )}

            {/* Error state */}
            {status === 'error' && (
              <div className="flex items-center gap-3 p-4 bg-red-500/10 border border-red-500/30 rounded-xl">
                <AlertCircle size={20} className="text-red-400 flex-shrink-0" />
                <div>
                  <p className="text-white text-sm font-medium">Remediation failed</p>
                  <p className="text-slate-400 text-xs mt-0.5">{result?.error}</p>
                </div>
              </div>
            )}

            {/* Approver input */}
            {status === 'idle' && (
              <div>
                <label className="block text-xs text-slate-400 font-medium mb-1.5">
                  Your name (approver) *
                </label>
                <input
                  type="text"
                  value={approvedBy}
                  onChange={(e) => setApprovedBy(e.target.value)}
                  placeholder="e.g. Jane Smith"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
                />
              </div>
            )}
          </div>

          {/* Footer */}
          {status === 'idle' && (
            <div className="px-6 py-4 border-t border-slate-700 flex justify-end gap-3 flex-shrink-0">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                disabled={!approvedBy.trim()}
                className="px-4 py-2 text-sm rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {isShared ? 'Confirm Flag for Review' : 'Confirm & Execute'}
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
