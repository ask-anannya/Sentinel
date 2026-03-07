import { useState } from 'react'
import { X, Shield, Loader2, CheckCircle, AlertCircle } from 'lucide-react'
import axios from 'axios'

const REMEDIATION_PREVIEWS = {
  ACCESS_VIOLATION: [
    'Navigate to user management page',
    'Locate user by username',
    'Click Edit/Disable link',
    'Click "Disable Account" button',
    'Confirm the action',
    'Verify account shows as Disabled',
  ],
  INACTIVE_ADMIN: [
    'Navigate to user management page',
    'Locate user by username',
    'Click Edit link',
    'Click "Deactivate Account" or remove admin privileges',
    'Confirm the action',
    'Verify change is reflected in user table',
  ],
  PERMISSION_CREEP: [
    'Navigate to user management page',
    'Locate user by username',
    'Click Edit link',
    'Revoke admin privileges or downgrade access level',
    'Save the changes',
    'Verify user no longer has elevated access',
  ],
  SHARED_ACCOUNT: [
    'Flag account for manual security review',
    'Document the shared account violation',
    'Notify security team for organizational decision',
    'No autonomous action taken (SOC2 CC6.3 compliance)',
  ],
}

export default function RemediationModal({ violation, onClose, onComplete }) {
  const [approvedBy, setApprovedBy] = useState('')
  const [status, setStatus] = useState('idle')  // idle | executing | success | error
  const [result, setResult] = useState(null)

  if (!violation) return null

  const steps = REMEDIATION_PREVIEWS[violation.violation_type] || []
  const isShared = violation.violation_type === 'SHARED_ACCOUNT'

  const handleConfirm = async () => {
    if (!approvedBy.trim()) return
    setStatus('executing')
    try {
      const { data } = await axios.post(
        `/api/violations/${violation.violation_id}/approve`,
        { approved_by: approvedBy.trim() }
      )
      setStatus('success')
      setResult(data)
      setTimeout(() => {
        onComplete?.()
      }, 2500)
    } catch (err) {
      setStatus('error')
      setResult({ error: err.response?.data?.detail || err.message })
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
         style={{ background: 'rgba(0,0,0,0.75)' }}>
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-lg shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
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

        {/* Body */}
        <div className="px-6 py-5 space-y-5">
          {/* Violation summary */}
          <div className="bg-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-400 uppercase tracking-wide font-medium mb-2">Violation</p>
            <p className="text-white font-medium">{violation.username} — {violation.violation_type}</p>
            <p className="text-slate-400 text-sm mt-1">{violation.tool_name} · {violation.severity}</p>
          </div>

          {/* What Nova Act will do */}
          <div>
            <p className="text-xs text-slate-400 uppercase tracking-wide font-medium mb-3">
              {isShared ? 'Actions that will be taken:' : 'Nova Act will execute these steps:'}
            </p>
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
          </div>

          {/* Approver */}
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

          {/* Executing state */}
          {status === 'executing' && (
            <div className="flex items-center gap-3 p-4 bg-blue-500/10 border border-blue-500/30 rounded-xl">
              <Loader2 size={20} className="text-blue-400 animate-spin flex-shrink-0" />
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
        </div>

        {/* Footer */}
        {status === 'idle' && (
          <div className="px-6 py-4 border-t border-slate-700 flex justify-end gap-3">
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
  )
}
