import { RadialBarChart, RadialBar, PolarAngleAxis } from 'recharts'

const scoreColor = (score) => {
  if (score >= 80) return '#22c55e'  // green
  if (score >= 60) return '#eab308'  // yellow
  return '#ef4444'                    // red
}

const scoreLabel = (score) => {
  if (score >= 80) return 'Compliant'
  if (score >= 60) return 'At Risk'
  return 'Critical'
}

export default function ComplianceScore({ score = 0, loading = false }) {
  const color = scoreColor(score)
  const data = [{ value: score, fill: color }]

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="animate-pulse text-slate-500 text-sm">Loading score...</div>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center">
      <div className="relative">
        <RadialBarChart
          width={200}
          height={200}
          cx={100}
          cy={100}
          innerRadius={65}
          outerRadius={90}
          barSize={20}
          data={data}
          startAngle={210}
          endAngle={-30}
        >
          <PolarAngleAxis
            type="number"
            domain={[0, 100]}
            angleAxisId={0}
            tick={false}
          />
          <RadialBar
            background={{ fill: '#1e293b' }}
            dataKey="value"
            angleAxisId={0}
            cornerRadius={8}
          />
        </RadialBarChart>
        {/* Center label */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-4xl font-bold" style={{ color }}>{score}</span>
          <span className="text-slate-400 text-xs mt-1">/100</span>
        </div>
      </div>
      <span
        className="mt-2 text-sm font-semibold px-3 py-1 rounded-full"
        style={{ background: color + '22', color }}
      >
        {scoreLabel(score)}
      </span>
    </div>
  )
}
