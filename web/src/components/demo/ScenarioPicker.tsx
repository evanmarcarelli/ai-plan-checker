import type { DemoScenario } from '@/data/demo-scenarios'

interface Props {
  scenarios: DemoScenario[]
  onSelect: (s: DemoScenario) => void
}

const ICONS: Record<string, string> = {
  'la-sfr-adu': '🏠',
  'sf-commercial-ti': '🏢',
  'seattle-dadu': '🏡',
}

const BADGE: Record<string, string> = {
  red: 'bg-red-100 text-red-700',
  blue: 'bg-blue-100 text-blue-700',
  slate: 'bg-slate-100 text-slate-600',
}

export default function ScenarioPicker({ scenarios, onSelect }: Props) {
  return (
    <div className="p-6">
      <p className="text-sm text-slate-500 text-center mb-5">
        Pick a submittal type to run through the AI triage engine
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {scenarios.map(s => (
          <button
            key={s.id}
            onClick={() => onSelect(s)}
            className="text-left p-4 bg-white border border-slate-200 rounded-xl hover:border-blue-400 hover:shadow-md transition-all group cursor-pointer"
          >
            <div className="text-2xl mb-2">{ICONS[s.id] ?? '📄'}</div>
            <h3 className="font-semibold text-slate-900 text-sm group-hover:text-blue-700 transition-colors">
              {s.label}
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">{s.location}</p>
            <p className="text-xs text-slate-400 mt-2 leading-snug">{s.description}</p>
            <div className="mt-3">
              <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${BADGE[s.badgeColor] ?? BADGE.slate}`}>
                {s.badgeText}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
