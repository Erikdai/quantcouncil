import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import type { Bar } from '@/api/types'
import { useI18n } from '@/i18n/I18nProvider'
import { normalizeRating, RATING_TONE, type Tone } from '@/lib/constants'
import { changeClass, fmtCompact, fmtPct, fmtPrice } from '@/lib/format'
import { cn } from '@/lib/cn'
import { cssVar, useTheme } from '@/lib/theme'

interface KlineChartProps {
  bars: Bar[]
  /** Analysis date; the marker goes on this bar (or the last bar before it). */
  markerDate?: string
  rating?: string | null
  height?: number
}

interface Palette {
  up: string
  down: string
  text: string
  grid: string
  border: string
  warn: string
  muted: string
}

function readPalette(): Palette {
  return {
    up: cssVar('--up', '#e03131'),
    down: cssVar('--down', '#0f9d58'),
    text: cssVar('--muted', '#6b7385'),
    grid: cssVar('--chart-grid', '#eef0f3'),
    border: cssVar('--line', '#e2e5ea'),
    warn: cssVar('--warn', '#d97706'),
    muted: cssVar('--muted', '#6b7385'),
  }
}

/** Add an alpha channel to a #rrggbb colour. */
function alpha(hex: string, a: number): string {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return hex
  return `${hex}${Math.round(a * 255)
    .toString(16)
    .padStart(2, '0')}`
}

function timeKey(t: Time): string {
  if (typeof t === 'string') return t
  if (typeof t === 'number') return new Date(t * 1000).toISOString().slice(0, 10)
  return `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}`
}

function buildMarker(bars: Bar[], date: string | undefined, label: string, tone: Tone | undefined, p: Palette) {
  if (!date || bars.length === 0) return []
  let target: Bar | undefined
  for (const b of bars) if (b.time <= date) target = b
  if (!target) return []
  const marker: SeriesMarker<Time> =
    tone === 'up'
      ? { time: target.time, position: 'belowBar', shape: 'arrowUp', color: p.up, text: label }
      : tone === 'down'
        ? { time: target.time, position: 'aboveBar', shape: 'arrowDown', color: p.down, text: label }
        : tone === 'warn'
          ? { time: target.time, position: 'aboveBar', shape: 'square', color: p.warn, text: label }
          : { time: target.time, position: 'aboveBar', shape: 'circle', color: p.muted, text: label }
  return [marker]
}

/** Daily candlesticks + volume. Up candles RED, down candles GREEN (A-share convention). */
export function KlineChart({ bars, markerDate, rating, height = 320 }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const { resolved } = useTheme()
  const { t, lang } = useI18n()
  const [hoverKey, setHoverKey] = useState<string | null>(null)
  const rated = normalizeRating(rating)
  const markerLabel = rated ? t(`rating.${rated}`) : t('chart.marker')
  const markerTone = rated ? RATING_TONE[rated] : undefined

  const index = useMemo(() => new Map(bars.map((b, i) => [b.time, i])), [bars])

  // Create the chart once.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const chart = createChart(el, {
      autoSize: true,
      localization: { dateFormat: 'yyyy-MM-dd' },
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, fontSize: 11 },
      rightPriceScale: { scaleMargins: { top: 0.08, bottom: 0.26 } },
      // Right padding leaves room for the rating marker's label on the last bar.
      timeScale: { rightOffset: 8, barSpacing: 6, fixLeftEdge: true },
      crosshair: { mode: CrosshairMode.Magnet },
    })
    const candle = chart.addSeries(CandlestickSeries, { borderVisible: false, priceLineVisible: false })
    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: 'volume',
      priceFormat: { type: 'volume' },
      lastValueVisible: false,
      priceLineVisible: false,
    })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })

    const onMove = (param: MouseEventParams<Time>) => {
      setHoverKey(param.time !== undefined ? timeKey(param.time) : null)
    }
    chart.subscribeCrosshairMove(onMove)

    chartRef.current = chart
    candleRef.current = candle
    volumeRef.current = volume
    markersRef.current = createSeriesMarkers(candle, [])

    return () => {
      chart.unsubscribeCrosshairMove(onMove)
      chart.remove()
      chartRef.current = null
      candleRef.current = null
      volumeRef.current = null
      markersRef.current = null
    }
  }, [])

  // Data + theme colours (canvas can't read CSS variables, so re-apply on theme change).
  useEffect(() => {
    const chart = chartRef.current
    const candle = candleRef.current
    const volume = volumeRef.current
    if (!chart || !candle || !volume) return
    const p = readPalette()

    chart.applyOptions({
      layout: { textColor: p.text },
      grid: { vertLines: { color: p.grid }, horzLines: { color: p.grid } },
      rightPriceScale: { borderColor: p.border },
      timeScale: { borderColor: p.border },
    })
    candle.applyOptions({ upColor: p.up, downColor: p.down, wickUpColor: p.up, wickDownColor: p.down })

    candle.setData(
      bars.map<CandlestickData<Time>>((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })),
    )
    volume.setData(
      bars.map<HistogramData<Time>>((b) => ({
        time: b.time,
        value: b.volume,
        color: alpha(b.close >= b.open ? p.up : p.down, 0.45),
      })),
    )
    chart.timeScale().fitContent()
  }, [bars, resolved])

  // Marker + axis locale: re-applied on language change without resetting the data or zoom.
  useEffect(() => {
    chartRef.current?.applyOptions({ localization: { locale: lang === 'zh' ? 'zh-CN' : 'en-US' } })
    markersRef.current?.setMarkers(buildMarker(bars, markerDate, markerLabel, markerTone, readPalette()))
  }, [bars, markerDate, markerLabel, markerTone, lang, resolved])

  // Legend: hovered bar, else the last bar.
  const i = hoverKey !== null ? index.get(hoverKey) : bars.length - 1
  const bar = i !== undefined ? bars[i] : undefined
  const prev = i !== undefined && i > 0 ? bars[i - 1] : undefined
  const chg = bar && prev ? bar.close / prev.close - 1 : null

  return (
    <div className="relative w-full" style={{ height }}>
      {bar && (
        <div className="pointer-events-none absolute top-1 left-2 z-10 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px] text-muted">
          <span className="text-fg-2">{bar.time}</span>
          <span>
            {t('chart.open')} <span className={changeClass(prev ? bar.open - prev.close : 0)}>{fmtPrice(bar.open)}</span>
          </span>
          <span>
            {t('chart.high')} <span className={changeClass(prev ? bar.high - prev.close : 0)}>{fmtPrice(bar.high)}</span>
          </span>
          <span>
            {t('chart.low')} <span className={changeClass(prev ? bar.low - prev.close : 0)}>{fmtPrice(bar.low)}</span>
          </span>
          <span>
            {t('chart.close')} <span className={changeClass(chg)}>{fmtPrice(bar.close)}</span>
          </span>
          {chg !== null && <span className={cn(changeClass(chg))}>{fmtPct(chg, { sign: true })}</span>}
          <span>
            {t('chart.volume')} {fmtCompact(bar.volume)}
          </span>
        </div>
      )}
      <div ref={containerRef} className="absolute inset-0" />
    </div>
  )
}
