import {
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Area, AreaChart,
} from 'recharts'
import { TrendingUp, TrendingDown } from 'lucide-react'

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function scoreColor(score) {
  if (score >= 80) return '#22c55e'   // green-500
  if (score >= 60) return '#eab308'   // yellow-500
  return '#ef4444'                    // red-500
}

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null
  const { score, event, timestamp } = payload[0].payload
  return (
    <div className="bg-slate-800 border border-slate-600 rounded-xl px-4 py-3 shadow-xl max-w-xs">
      <p className="text-white font-bold text-lg">{score}<span className="text-slate-400 text-sm font-normal"> / 100</span></p>
      <p className="text-slate-300 text-xs mt-1 leading-snug">{event}</p>
      <p className="text-slate-500 text-xs mt-1">{new Date(timestamp).toLocaleString()}</p>
    </div>
  )
}

const CustomDot = (props) => {
  const { cx, cy, payload } = props
  const color = scoreColor(payload.score)
  return (
    <circle cx={cx} cy={cy} r={5} fill={color} stroke="#0f172a" strokeWidth={2} />
  )
}

export default function ScoreTrendChart({ data = [] }) {
  if (data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-slate-500">
        <TrendingUp size={28} className="mb-2 opacity-30" />
        <p className="text-sm">Run a scan to see score history</p>
      </div>
    )
  }

  const latest = data[data.length - 1]
  const first = data[0]
  const delta = latest.score - first.score
  const lineColor = scoreColor(latest.score)

  // Recharts needs plain objects with numeric y
  const chartData = data.map(d => ({ ...d, y: d.score }))

  return (
    <div>
      {/* Header row */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-2xl font-bold" style={{ color: lineColor }}>{latest.score}</p>
          <p className="text-slate-500 text-xs">current score</p>
        </div>
        <div className={`flex items-center gap-1.5 text-sm font-medium ${delta >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {delta >= 0
            ? <TrendingUp size={16} />
            : <TrendingDown size={16} />
          }
          {delta >= 0 ? '+' : ''}{delta} pts this session
        </div>
      </div>

      <ResponsiveContainer width="100%" height={180}>
        <AreaChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id="scoreGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={lineColor} stopOpacity={0.25} />
              <stop offset="95%" stopColor={lineColor} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
          <XAxis
            dataKey="timestamp"
            tickFormatter={formatTime}
            tick={{ fill: '#64748b', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fill: '#64748b', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            ticks={[0, 25, 50, 75, 100]}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ stroke: '#334155', strokeWidth: 1 }} />
          <ReferenceLine y={80} stroke="#22c55e" strokeDasharray="4 4" strokeOpacity={0.3} />
          <ReferenceLine y={60} stroke="#eab308" strokeDasharray="4 4" strokeOpacity={0.3} />
          <Area
            type="monotone"
            dataKey="y"
            stroke={lineColor}
            strokeWidth={2.5}
            fill="url(#scoreGradient)"
            dot={<CustomDot />}
            activeDot={{ r: 7, fill: lineColor, stroke: '#0f172a', strokeWidth: 2 }}
            isAnimationActive={true}
            animationDuration={800}
          />
        </AreaChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div className="flex gap-4 mt-3 justify-end">
        <div className="flex items-center gap-1.5">
          <div className="w-6 border-t border-dashed border-green-500/40" />
          <span className="text-slate-500 text-xs">Good (80+)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-6 border-t border-dashed border-yellow-500/40" />
          <span className="text-slate-500 text-xs">Fair (60+)</span>
        </div>
      </div>
    </div>
  )
}
