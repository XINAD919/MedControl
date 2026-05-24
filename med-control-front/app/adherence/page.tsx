'use client'

import { useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { RefreshCw, TrendingUp, TrendingDown, Minus, Clock, CheckCircle2, Pill, AlertCircle } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { fetchLatestAdherenceAnalysis, generateAdherenceAnalysis } from '../lib/api'
import type { AdherenceAnalysis } from '../lib/types'

// ── Score helpers ─────────────────────────────────────────────────────────────

const SCORE_CONFIG: Record<string, { label: string; bg: string; text: string; ring: string }> = {
  excellent: { label: 'Excelente',   bg: 'bg-green-50',  text: 'text-green-700',  ring: 'ring-green-400' },
  good:      { label: 'Muy bueno',   bg: 'bg-blue-50',   text: 'text-blue-700',   ring: 'ring-blue-400'  },
  regular:   { label: 'Regular',     bg: 'bg-yellow-50', text: 'text-yellow-700', ring: 'ring-yellow-400'},
  poor:      { label: 'Deficiente',  bg: 'bg-orange-50', text: 'text-orange-700', ring: 'ring-orange-400'},
  critical:  { label: 'Crítico',     bg: 'bg-red-50',    text: 'text-red-700',    ring: 'ring-red-400'   },
}

function scoreConfig(score: number) {
  if (score >= 4.5) return SCORE_CONFIG.excellent
  if (score >= 3.5) return SCORE_CONFIG.good
  if (score >= 2.5) return SCORE_CONFIG.regular
  if (score >= 1.5) return SCORE_CONFIG.poor
  return SCORE_CONFIG.critical
}

const SCORE_BAR_COLOR: Record<string, string> = {
  excellent: 'bg-green-400',
  good:      'bg-blue-400',
  regular:   'bg-yellow-400',
  poor:      'bg-orange-400',
  critical:  'bg-red-400',
}

function scoreBarColor(score: number) {
  if (score >= 4.5) return SCORE_BAR_COLOR.excellent
  if (score >= 3.5) return SCORE_BAR_COLOR.good
  if (score >= 2.5) return SCORE_BAR_COLOR.regular
  if (score >= 1.5) return SCORE_BAR_COLOR.poor
  return SCORE_BAR_COLOR.critical
}

function pct(rate: number) {
  return `${Math.round(rate * 100)}%`
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('es-CO', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ScoreCard({ analysis }: { analysis: AdherenceAnalysis }) {
  const cfg = scoreConfig(analysis.score)
  const barPct = ((analysis.score - 1) / 4) * 100

  return (
    <div className={`rounded-2xl p-6 ${cfg.bg} ring-2 ${cfg.ring} flex flex-col items-center gap-3`}>
      <p className="text-sm font-semibold text-gray-500 uppercase tracking-wider">Puntuación de Adherencia</p>
      <div className="flex items-end gap-1">
        <span className={`text-7xl font-black ${cfg.text}`}>{analysis.score.toFixed(1)}</span>
        <span className="text-2xl text-gray-400 mb-2">/5</span>
      </div>
      <span className={`px-3 py-1 rounded-full text-sm font-semibold ${cfg.bg} ${cfg.text} ring-1 ${cfg.ring}`}>
        {cfg.label}
      </span>
      {/* Progress bar */}
      <div className="w-full max-w-xs bg-gray-200 rounded-full h-2.5 mt-1">
        <div
          className={`h-2.5 rounded-full transition-all duration-700 ${scoreBarColor(analysis.score)}`}
          style={{ width: `${barPct}%` }}
        />
      </div>
      <p className="text-xs text-gray-400">
        Análisis de los últimos {analysis.period_days} días · {formatDate(analysis.created_at)}
      </p>
    </div>
  )
}

function MetricCard({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode
  label: string
  value: string
  sub?: string
}) {
  return (
    <div className="bg-white rounded-xl p-4 border border-gray-100 shadow-sm flex items-start gap-3">
      <div className="shrink-0 mt-0.5 text-blue-500">{icon}</div>
      <div>
        <p className="text-xs text-gray-400 font-medium">{label}</p>
        <p className="text-xl font-bold text-gray-900 mt-0.5">{value}</p>
        {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

function TrendIcon({ trend }: { trend: string }) {
  if (trend === 'mejorando') return <TrendingUp size={18} className="text-green-500" />
  if (trend === 'empeorando') return <TrendingDown size={18} className="text-red-500" />
  return <Minus size={18} className="text-gray-400" />
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AdherencePage() {
  const { data: session } = useSession()
  const [analysis, setAnalysis] = useState<AdherenceAnalysis | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!session) return
    fetchLatestAdherenceAnalysis(session)
      .then(setAnalysis)
      .catch(() => setAnalysis(null))
      .finally(() => setLoading(false))
  }, [session])

  async function handleGenerate() {
    if (!session) return
    setGenerating(true)
    setError(null)
    try {
      const result = await generateAdherenceAnalysis(session, 30)
      setAnalysis(result)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Error al generar el análisis'
      setError(msg.includes('suficiente') ? 'No hay suficiente historial de medicamentos para generar un análisis.' : msg)
    } finally {
      setGenerating(false)
    }
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3 text-gray-400">
          <RefreshCw size={28} className="animate-spin" />
          <p className="text-sm">Cargando análisis…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 sm:p-6 bg-gray-50">
      <div className="max-w-2xl mx-auto flex flex-col gap-6 pt-12 sm:pt-0">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Análisis de Adherencia</h1>
            <p className="text-sm text-gray-400 mt-0.5">Evaluación del comportamiento de toma de medicamentos</p>
          </div>
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating}
            className="flex items-center gap-2 px-4 py-2 bg-blue-500 text-white text-sm font-semibold rounded-xl hover:bg-blue-600 disabled:opacity-60 disabled:cursor-not-allowed transition-colors shadow-sm"
          >
            <RefreshCw size={15} className={generating ? 'animate-spin' : ''} />
            {generating ? 'Analizando...' : analysis ? 'Regenerar' : 'Generar Análisis'}
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="flex items-start gap-2 bg-red-50 border border-red-100 rounded-xl px-4 py-3 text-sm text-red-700">
            <AlertCircle size={16} className="shrink-0 mt-0.5" />
            {error}
          </div>
        )}

        {/* Empty state */}
        {!analysis && !generating && !error && (
          <div className="bg-white rounded-2xl border border-gray-100 p-10 flex flex-col items-center gap-4 text-center shadow-sm">
            <div className="size-14 rounded-full bg-blue-50 flex items-center justify-center">
              <Pill size={26} className="text-blue-400" />
            </div>
            <div>
              <p className="font-semibold text-gray-700">Sin análisis previo</p>
              <p className="text-sm text-gray-400 mt-1">
                Presiona <span className="font-medium text-blue-500">Generar Análisis</span> para evaluar tu comportamiento de los últimos 30 días…
              </p>
            </div>
          </div>
        )}

        {/* Generating skeleton */}
        {generating && (
          <div className="bg-white rounded-2xl border border-gray-100 p-10 flex flex-col items-center gap-4 text-center shadow-sm animate-pulse">
            <div className="size-14 rounded-full bg-blue-100" />
            <div className="h-4 bg-gray-100 rounded w-48" />
            <div className="h-3 bg-gray-100 rounded w-64" />
          </div>
        )}

        {/* Analysis result */}
        {analysis && !generating && (
          <>
            <ScoreCard analysis={analysis} />

            {/* Metrics grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <MetricCard
                icon={<CheckCircle2 size={18} />}
                label="Adherencia global"
                value={pct(analysis.metrics.adherence_rate)}
                sub={`${analysis.metrics.total_taken} de ${analysis.metrics.total_due} dosis`}
              />
              <MetricCard
                icon={<Clock size={18} />}
                label="Puntualidad"
                value={pct(analysis.metrics.punctuality_rate)}
                sub={`Retraso promedio: ${analysis.metrics.avg_delay_minutes} min`}
              />
              <MetricCard
                icon={<TrendIcon trend={analysis.metrics.trend} />}
                label="Tendencia reciente"
                value={pct(analysis.metrics.recent_adherence_rate)}
                sub={`Últimos 7 días · ${analysis.metrics.trend}`}
              />
              <MetricCard
                icon={<Pill size={18} />}
                label="Medicamentos"
                value={String(analysis.metrics.medications.length)}
                sub={analysis.metrics.medications.join(', ') || '—'}
              />
            </div>

            {/* LLM comment */}
            <div className="bg-white rounded-2xl border border-blue-100 p-5 shadow-sm">
              <p className="text-xs font-semibold text-blue-400 uppercase tracking-wider mb-2">Análisis del asistente</p>
              <div className="md-prose text-sm">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{analysis.llm_comment}</ReactMarkdown>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
