import { useState, useEffect, useCallback } from 'react'
import { Download, Image, Filter } from 'lucide-react'
import axios from 'axios'

const EVENT_LABELS = {
  scan_started:         { label: 'Scan Started',     color: 'bg-blue-500/20 text-blue-300' },
  scan_completed:       { label: 'Scan Completed',   color: 'bg-green-500/20 text-green-300' },
  violation_detected:   { label: 'Violation',        color: 'bg-orange-500/20 text-orange-300' },
  remediation_approved: { label: 'Remediation',      color: 'bg-purple-500/20 text-purple-300' },
  violation_dismissed:  { label: 'Dismissed',        color: 'bg-slate-500/20 text-slate-400' },
}

const RESULT_COLORS = {
  success:       'text-green-400',
  failed:        'text-red-400',
  started:       'text-blue-400',
  dismissed:     'text-slate-400',
  manual_review: 'text-orange-400',
}

export default function AuditTrail() {
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [filterType, setFilterType] = useState('')
  const [screenshotModal, setScreenshotModal] = useState(null)

  const fetchAuditTrail = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await axios.get('/api/audit-trail')
      setEntries(data)
    } catch (err) {
      console.error('Failed to fetch audit trail:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchAuditTrail() }, [fetchAuditTrail])

  const handleExport = async () => {
    setExporting(true)
    try {
      const response = await axios.get('/api/reports/export', { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.download = `sentinel_audit_${new Date().toISOString().slice(0, 10)}.pdf`
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Export failed:', err)
      alert('Export failed. Make sure the backend is running with valid AWS credentials.')
    } finally {
      setExporting(false)
    }
  }

  const filtered = filterType
    ? entries.filter(e => e.event_type === filterType)
    : entries

  const uniqueTypes = [...new Set(entries.map(e => e.event_type))]

  return (
    <div className="p-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Audit Trail</h1>
          <p className="text-slate-400 text-sm mt-1">
            Complete history of scans, violations, and remediations
          </p>
        </div>
        <button
          onClick={handleExport}
          disabled={exporting}
          className="flex items-center gap-2 px-4 py-2 text-sm bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 rounded-xl transition-colors disabled:opacity-50"
        >
          <Download size={14} />
          {exporting ? 'Generating...' : 'Export Report'}
        </button>
      </div>

      {/* Filter */}
      <div className="flex items-center gap-3 mb-5">
        <Filter size={14} className="text-slate-400" />
        <select
          value={filterType}
          onChange={e => setFilterType(e.target.value)}
          className="bg-slate-800 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-blue-500"
        >
          <option value="">All event types</option>
          {uniqueTypes.map(t => (
            <option key={t} value={t}>{EVENT_LABELS[t]?.label || t}</option>
          ))}
        </select>
        <span className="text-xs text-slate-500">{filtered.length} entries</span>
      </div>

      {/* Table */}
      {loading ? (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-14 bg-slate-800 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-20">
          <p className="text-slate-400">No audit entries yet.</p>
          <p className="text-slate-500 text-sm mt-1">Run a scan to start recording events.</p>
        </div>
      ) : (
        <div className="bg-slate-900 border border-slate-700 rounded-2xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700 bg-slate-800/50">
                <th className="text-left px-5 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Timestamp</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Event</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Action</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Actor</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Result</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-slate-400 uppercase tracking-wider">Evidence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {filtered.map((entry) => {
                const eventMeta = EVENT_LABELS[entry.event_type] || { label: entry.event_type, color: 'bg-slate-700 text-slate-300' }
                const resultColor = RESULT_COLORS[entry.result] || 'text-slate-400'
                return (
                  <tr key={entry.entry_id} className="hover:bg-slate-800/50 transition-colors">
                    <td className="px-5 py-3 text-xs text-slate-400 whitespace-nowrap font-mono">
                      {new Date(entry.timestamp).toLocaleString()}
                    </td>
                    <td className="px-5 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${eventMeta.color}`}>
                        {eventMeta.label}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-slate-300 max-w-xs">
                      <p className="truncate">{entry.action}</p>
                      {entry.details && (
                        <p className="text-xs text-slate-500 mt-0.5 truncate">{entry.details}</p>
                      )}
                    </td>
                    <td className="px-5 py-3 text-slate-400 text-xs">{entry.actor || '—'}</td>
                    <td className={`px-5 py-3 text-xs font-medium ${resultColor}`}>
                      {entry.result || '—'}
                    </td>
                    <td className="px-5 py-3">
                      {entry.screenshot_path ? (
                        <button
                          onClick={() => setScreenshotModal(entry.screenshot_path)}
                          className="text-blue-400 hover:text-blue-300 transition-colors flex items-center gap-1 text-xs"
                        >
                          <Image size={12} /> View
                        </button>
                      ) : (
                        <span className="text-slate-600 text-xs">—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
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
            <p className="text-slate-400 text-sm mb-3">Screenshot: {screenshotModal}</p>
            <img
              src={`/api/screenshots/${screenshotModal}`}
              alt="Audit screenshot"
              className="w-full rounded-lg"
              onError={(e) => { e.target.alt = 'Screenshot not available' }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
