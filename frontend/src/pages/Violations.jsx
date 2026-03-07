import { useState, useEffect, useCallback } from 'react'
import { Filter, X } from 'lucide-react'
import axios from 'axios'
import ViolationCard from '../components/ViolationCard.jsx'
import RemediationModal from '../components/RemediationModal.jsx'

const SEVERITIES = ['', 'CRITICAL', 'HIGH', 'MEDIUM']
const TOOLS = ['', 'hr-portal', 'it-admin', 'procurement']
const STATUSES = ['', 'open', 'resolved', 'dismissed']

export default function Violations() {
  const [violations, setViolations] = useState([])
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState({ severity: '', tool: '', status: 'open' })
  const [remediateViolation, setRemediateViolation] = useState(null)
  const [dismissTarget, setDismissTarget] = useState(null)
  const [dismissReason, setDismissReason] = useState('')
  const [dismissName, setDismissName] = useState('')
  const [screenshotModal, setScreenshotModal] = useState(null)

  const fetchViolations = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (filters.severity) params.severity = filters.severity
      if (filters.tool) params.tool = filters.tool
      if (filters.status) params.status = filters.status
      const { data } = await axios.get('/api/violations', { params })
      setViolations(data)
    } catch (err) {
      console.error('Failed to fetch violations:', err)
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => { fetchViolations() }, [fetchViolations])

  const handleDismiss = async () => {
    if (!dismissTarget || !dismissReason.trim() || !dismissName.trim()) return
    try {
      await axios.post(`/api/violations/${dismissTarget.violation_id}/dismiss`, {
        dismissed_by: dismissName.trim(),
        reason: dismissReason.trim(),
      })
      setDismissTarget(null)
      setDismissReason('')
      setDismissName('')
      fetchViolations()
    } catch (err) {
      console.error('Dismiss failed:', err)
    }
  }

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Violations</h1>
        <p className="text-slate-400 text-sm mt-1">
          {violations.length} violation{violations.length !== 1 ? 's' : ''} matching current filters
        </p>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <Filter size={14} className="text-slate-400" />
        {[
          { key: 'severity', options: SEVERITIES, label: 'Severity' },
          { key: 'tool', options: TOOLS, label: 'Tool' },
          { key: 'status', options: STATUSES, label: 'Status' },
        ].map(({ key, options, label }) => (
          <select
            key={key}
            value={filters[key]}
            onChange={(e) => setFilters(f => ({ ...f, [key]: e.target.value }))}
            className="bg-slate-800 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-blue-500"
          >
            <option value="">{label}: All</option>
            {options.filter(Boolean).map(o => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        ))}
        {(filters.severity || filters.tool || filters.status !== 'open') && (
          <button
            onClick={() => setFilters({ severity: '', tool: '', status: 'open' })}
            className="text-xs text-slate-400 hover:text-white flex items-center gap-1 transition-colors"
          >
            <X size={12} /> Reset
          </button>
        )}
      </div>

      {/* Violation list */}
      {loading ? (
        <div className="space-y-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-32 bg-slate-800 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : violations.length === 0 ? (
        <div className="text-center py-20">
          <div className="text-slate-600 text-4xl mb-4">✓</div>
          <p className="text-slate-400 text-lg font-medium">No violations found</p>
          <p className="text-slate-500 text-sm mt-1">Run a scan to check for compliance issues</p>
        </div>
      ) : (
        <div className="space-y-4">
          {violations.map((v) => (
            <ViolationCard
              key={v.violation_id}
              violation={v}
              onRemediate={() => setRemediateViolation(v)}
              onDismiss={() => setDismissTarget(v)}
              onViewScreenshot={(path) => setScreenshotModal(path)}
            />
          ))}
        </div>
      )}

      {/* Remediation modal */}
      {remediateViolation && (
        <RemediationModal
          violation={remediateViolation}
          onClose={() => setRemediateViolation(null)}
          onComplete={() => {
            setRemediateViolation(null)
            fetchViolations()
          }}
        />
      )}

      {/* Dismiss dialog */}
      {dismissTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ background: 'rgba(0,0,0,0.75)' }}>
          <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-md p-6">
            <h3 className="text-white font-semibold mb-1">Dismiss Violation</h3>
            <p className="text-slate-400 text-sm mb-4">
              Dismiss: <span className="text-white">{dismissTarget.username} — {dismissTarget.violation_type}</span>
            </p>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Your name *</label>
                <input
                  type="text"
                  value={dismissName}
                  onChange={e => setDismissName(e.target.value)}
                  placeholder="e.g. Security Analyst"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Reason for dismissal *</label>
                <textarea
                  value={dismissReason}
                  onChange={e => setDismissReason(e.target.value)}
                  placeholder="Explain why this violation is being dismissed..."
                  rows={3}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 resize-none"
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-5">
              <button
                onClick={() => { setDismissTarget(null); setDismissReason(''); setDismissName('') }}
                className="px-4 py-2 text-sm rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300"
              >
                Cancel
              </button>
              <button
                onClick={handleDismiss}
                disabled={!dismissReason.trim() || !dismissName.trim()}
                className="px-4 py-2 text-sm rounded-lg bg-slate-600 hover:bg-slate-500 text-white font-medium disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Dismiss Violation
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Screenshot modal */}
      {screenshotModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: 'rgba(0,0,0,0.85)' }}
          onClick={() => setScreenshotModal(null)}
        >
          <div className="bg-slate-900 border border-slate-700 rounded-xl max-w-4xl w-full p-4">
            <div className="flex justify-between items-center mb-3">
              <span className="text-slate-400 text-sm">Scan Screenshot</span>
              <button onClick={() => setScreenshotModal(null)} className="text-slate-400 hover:text-white">
                <X size={18} />
              </button>
            </div>
            <img
              src={`/api/screenshots/${screenshotModal}`}
              alt="Scan screenshot"
              className="w-full rounded-lg"
              onError={(e) => { e.target.src = ''; e.target.alt = 'Screenshot not available' }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
