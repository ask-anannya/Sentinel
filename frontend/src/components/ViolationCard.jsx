import { AlertCircle, AlertTriangle, Info, Database, Monitor, ShoppingCart, ChevronRight } from 'lucide-react'

const SEVERITY_STYLES = {
  CRITICAL: { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400', badge: 'bg-red-500', icon: AlertCircle },
  HIGH:     { bg: 'bg-orange-500/10', border: 'border-orange-500/30', text: 'text-orange-400', badge: 'bg-orange-500', icon: AlertTriangle },
  MEDIUM:   { bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', text: 'text-yellow-400', badge: 'bg-yellow-500', icon: Info },
}

const TOOL_ICONS = {
  'hr-portal':    { icon: Database, label: 'HRMS v3.1' },
  'it-admin':     { icon: Monitor, label: 'IT Admin v2.4' },
  'procurement':  { icon: ShoppingCart, label: 'Procurement v1.8' },
}

const SOC2_TOOLTIPS = {
  'CC6.1': 'CC6.1 — Logical and Physical Access Controls: The entity implements logical access security measures to protect against unauthorized access.',
  'CC6.2': 'CC6.2 — User Access Provisioning and Deprovisioning: The entity manages access credentials for personnel and removes access upon termination.',
  'CC6.3': 'CC6.3 — Access Role Management: The entity authorizes and manages role-based access and restricts privileged access.',
}

const VIOLATION_LABELS = {
  ACCESS_VIOLATION: 'Access Violation',
  INACTIVE_ADMIN:   'Inactive Admin',
  SHARED_ACCOUNT:   'Shared Account',
  PERMISSION_CREEP: 'Permission Creep',
}

export default function ViolationCard({ violation, onRemediate, onDismiss, onViewScreenshot }) {
  const severity = violation.severity || 'MEDIUM'
  const styles = SEVERITY_STYLES[severity] || SEVERITY_STYLES.MEDIUM
  const SeverityIcon = styles.icon
  const toolInfo = TOOL_ICONS[violation.tool_name] || { icon: Database, label: violation.tool_name }
  const ToolIcon = toolInfo.icon

  const isOpen = violation.status === 'open'

  return (
    <div className={`rounded-xl border p-5 ${styles.bg} ${styles.border} transition-all hover:shadow-lg hover:shadow-black/20`}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className={`p-2 rounded-lg ${styles.bg} border ${styles.border}`}>
            <SeverityIcon size={16} className={styles.text} />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-xs font-bold uppercase tracking-wide px-2 py-0.5 rounded ${styles.badge} text-white`}>
                {severity}
              </span>
              <span className="text-xs text-slate-400 bg-slate-700 px-2 py-0.5 rounded">
                {VIOLATION_LABELS[violation.violation_type] || violation.violation_type}
              </span>
              <span
                className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded font-mono cursor-help underline decoration-dotted decoration-slate-600"
                title={SOC2_TOOLTIPS[violation.soc2_control] || violation.soc2_control}
              >
                {violation.soc2_control}
              </span>
            </div>
            <div className="mt-1.5">
              <span className="text-white font-semibold">{violation.username}</span>
              {violation.full_name && (
                <span className="text-slate-400 text-sm ml-2">— {violation.full_name}</span>
              )}
            </div>
            <div className="flex items-center gap-2 mt-1 text-xs text-slate-500">
              <ToolIcon size={12} />
              <span>{toolInfo.label}</span>
              {violation.department && <span>· {violation.department}</span>}
              {violation.role && <span>· {violation.role}</span>}
            </div>
          </div>
        </div>

        {/* Status pill */}
        <div className={`text-xs px-2.5 py-1 rounded-full font-medium shrink-0 ${
          violation.status === 'open'
            ? 'bg-slate-700 text-slate-300'
            : violation.status === 'resolved'
            ? 'bg-green-500/20 text-green-400'
            : 'bg-slate-600 text-slate-400'
        }`}>
          {violation.status}
        </div>
      </div>

      {/* Evidence */}
      {violation.evidence && (
        <p className="mt-3 text-sm text-slate-300 leading-relaxed">
          {violation.evidence}
        </p>
      )}

      {/* Detected at */}
      <p className="mt-2 text-xs text-slate-500">
        Detected: {new Date(violation.detected_at).toLocaleString()}
        {violation.resolved_by && ` · Resolved by: ${violation.resolved_by}`}
      </p>

      {/* Actions */}
      {isOpen && (
        <div className="mt-4 flex items-center gap-2 flex-wrap">
          {violation.screenshot_path && (
            <button
              onClick={() => onViewScreenshot?.(violation.screenshot_path)}
              className="text-xs px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors flex items-center gap-1.5"
            >
              View Screenshot
            </button>
          )}
          {violation.violation_type !== 'SHARED_ACCOUNT' && (
            <button
              onClick={() => onRemediate?.(violation)}
              className="text-xs px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors font-medium flex items-center gap-1.5"
            >
              Remediate <ChevronRight size={12} />
            </button>
          )}
          {violation.violation_type === 'SHARED_ACCOUNT' && (
            <button
              onClick={() => onRemediate?.(violation)}
              className="text-xs px-3 py-1.5 rounded-lg bg-orange-600 hover:bg-orange-500 text-white transition-colors font-medium"
            >
              Flag for Review
            </button>
          )}
          <button
            onClick={() => onDismiss?.(violation)}
            className="text-xs px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-300 transition-colors"
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  )
}
