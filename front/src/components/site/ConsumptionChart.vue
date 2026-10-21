<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Line } from 'vue-chartjs'
import {
  CategoryScale,
  Chart as ChartJS,
  Filler,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
  type ChartData,
  type ChartOptions,
  type Plugin,
} from 'chart.js'

import { formatKw } from '@/lib/format'
import type { SiteSeries } from '@/types/energy'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip)

const props = defineProps<{
  series: SiteSeries
  capaciteKw: number
  seuilPct?: number
}>()

const seuil = computed(() => (props.capaciteKw * (props.seuilPct ?? 90)) / 100)

// Chart.js dessine sur un canvas : il lui faut les couleurs réelles, pas les classes Tailwind
const colors = ref({
  ink: '#1f2933',
  muted: '#616b78',
  band: 'rgba(97,107,120,0.18)',
  grid: '#e4e7eb',
})
onMounted(() => {
  const css = getComputedStyle(document.documentElement)
  const v = (name: string) => css.getPropertyValue(name).trim()
  colors.value = {
    ink: v('--chart-1') || colors.value.ink,
    muted: v('--chart-2') || colors.value.muted,
    band: `color-mix(in oklch, ${v('--chart-3') || '#c9ced6'} 70%, transparent)`,
    grid: v('--border') || colors.value.grid,
  }
})

// Un seul axe horaire : les mesures, puis les prédictions.
// Le dernier point mesuré sert aussi de départ à la prédiction, pour que les courbes se rejoignent.
const points = computed(() => {
  const { mesures, predictions } = props.series
  const last = mesures.length - 1
  return [
    ...mesures.map((m, i) => {
      const junction = i === last ? m.kw : null
      return { t: m.horodatage, mesure: m.kw, pred: junction, basse: junction, haute: junction }
    }),
    ...predictions.slice(1).map((p) => ({
      t: p.horodatage,
      mesure: null,
      pred: p.kw,
      basse: p.basseKw,
      haute: p.hauteKw,
    })),
  ]
})

const nowIndex = computed(() => props.series.mesures.length - 1)

const peak = computed(() => {
  let best = { index: -1, kw: -Infinity }
  points.value.forEach((p, index) => {
    if (index > nowIndex.value && p.pred !== null && p.pred > best.kw) best = { index, kw: p.pred }
  })
  return best
})

const labels = computed(() =>
  points.value.map((p) => {
    const d = new Date(p.t)
    return `${d.toLocaleDateString('fr-FR', { weekday: 'short' })} ${d.getHours()} h`
  }),
)

const data = computed<ChartData<'line'>>(() => ({
  labels: labels.value,
  datasets: [
    {
      label: 'Fourchette basse',
      data: points.value.map((p) => p.basse),
      borderWidth: 0,
      pointRadius: 0,
    },
    {
      label: 'Fourchette haute',
      data: points.value.map((p) => p.haute),
      borderWidth: 0,
      pointRadius: 0,
      backgroundColor: colors.value.band,
      fill: '-1', // remplit jusqu'à la fourchette basse
    },
    {
      label: 'Mesures réelles',
      data: points.value.map((p) => p.mesure),
      borderColor: colors.value.ink,
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.2,
    },
    {
      label: 'Prédiction',
      data: points.value.map((p) => p.pred),
      borderColor: colors.value.ink,
      borderWidth: 2,
      borderDash: [6, 5],
      tension: 0.35,
      pointRadius: points.value.map((_, i) => (i === peak.value.index ? 6 : 0)),
      pointBorderWidth: 2,
      pointBackgroundColor: 'transparent',
      pointBorderColor: colors.value.ink,
    },
    {
      label: `${props.seuilPct ?? 90} % de la capacité`,
      data: points.value.map(() => seuil.value),
      borderColor: colors.value.muted,
      borderWidth: 1,
      borderDash: [4, 4],
      pointRadius: 0,
    },
  ],
}))

// Ligne verticale « maintenant » (pas besoin du plugin d'annotations pour un seul trait)
const nowLine: Plugin<'line'> = {
  id: 'nowLine',
  afterDatasetsDraw(chart) {
    const x = chart.scales.x?.getPixelForValue(nowIndex.value)
    const { top, bottom } = chart.chartArea
    if (x === undefined) return
    const ctx = chart.ctx
    ctx.save()
    ctx.strokeStyle = colors.value.muted
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(x, top)
    ctx.lineTo(x, bottom)
    ctx.stroke()
    ctx.fillStyle = colors.value.muted
    ctx.font = '12px Inter Variable, sans-serif'
    ctx.fillText('maintenant', x + 6, top + 12)
    ctx.restore()
  },
}

const options = computed<ChartOptions<'line'>>(() => ({
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  scales: {
    x: {
      grid: { display: false },
      ticks: { maxTicksLimit: 8, color: colors.value.muted, maxRotation: 0 },
    },
    y: {
      beginAtZero: false,
      grid: { color: colors.value.grid },
      ticks: { color: colors.value.muted, callback: (v) => formatKw(Number(v)) },
    },
  },
  plugins: {
    legend: { display: false },
    tooltip: {
      filter: (item) => item.raw !== null && item.datasetIndex >= 2,
      callbacks: { label: (item) => `${item.dataset.label} : ${formatKw(Number(item.raw))}` },
    },
  },
}))
</script>

<template>
  <div>
    <div class="h-72 sm:h-80">
      <Line :data="data" :options="options" :plugins="[nowLine]" />
    </div>
    <ul class="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted-foreground">
      <li class="flex items-center gap-2">
        <span class="h-0.5 w-5 bg-foreground" aria-hidden="true" /> mesures réelles
      </li>
      <li class="flex items-center gap-2">
        <span class="w-5 border-t-2 border-dashed border-foreground" aria-hidden="true" />
        prédiction
      </li>
      <li class="flex items-center gap-2">
        <span class="h-3 w-5 rounded-sm bg-chart-3/70" aria-hidden="true" /> fourchette (valeur
        basse – valeur haute)
      </li>
    </ul>
  </div>
</template>
