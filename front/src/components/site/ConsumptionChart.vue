<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { Line } from 'vue-chartjs'
import { useIntervalFn, useMediaQuery, useNow } from '@vueuse/core'
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

import { MINUTES_RECONSTITUEES_MARQUEES } from '@/lib/etat'
import { formatAxisHour, formatEurCents, formatKwh, formatKw } from '@/lib/format'
import { buildChartPoints, nowIndexOf, peakOnAxis } from '@/lib/chartPoints'
import type { SiteSeries } from '@/types/energy'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip)

const props = defineProps<{
  series: SiteSeries
  capaciteKw: number
  seuilPct?: number
}>()

const seuil = computed(() => (props.capaciteKw * (props.seuilPct ?? 90)) / 100)

// Chart.js dessine sur un canvas : il lui faut les couleurs réelles, pas les classes Tailwind.
// Elles sont relues si le thème change (classe « dark » sur <html>).
const colors = ref(readColors())

function readColors() {
  const css = getComputedStyle(document.documentElement)
  const v = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback
  return {
    ink: v('--chart-canvas-line', '#1f2937'),
    muted: v('--chart-canvas-muted', '#6b7280'),
    band: v('--chart-canvas-band', 'rgba(156, 163, 175, 0.35)'),
    grid: v('--chart-canvas-grid', '#e5e7eb'),
  }
}

const themeObserver = new MutationObserver(() => (colors.value = readColors()))
onMounted(() =>
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] }),
)
onBeforeUnmount(() => themeObserver.disconnect())

// Axe horaire : mesures, heure en cours, prévisions (lib/chartPoints.ts)
const points = computed(() => buildChartPoints(props.series))

// La fourchette n'est dessinée (et légendée) que si le modèle en donne une
const hasBand = computed(() =>
  props.series.predictions.some((p) => p.basseKw !== null && p.hauteKw !== null),
)

// US4 : heures dont une part notable des minutes a été reconstituée après une panne. Marquées
// d'un point creux sur la courbe : la valeur est en partie estimée, pas mesurée. Les quelques
// minutes isolées interpolées presque chaque heure ne sont pas marquées (la courbe serait
// couverte de points) ; l'infobulle donne toujours le nombre exact.
const isImputed = (p: { mesure: number | null; imputees: number }) =>
  p.mesure !== null && p.imputees >= MINUTES_RECONSTITUEES_MARQUEES
const hasImputed = computed(() => points.value.some(isImputed))

// Horloge relue chaque minute : « maintenant » passe à l'heure suivante même si les données
// ne sont pas encore rechargées
const now = useNow({ scheduler: (cb) => useIntervalFn(cb, 60_000) })
const nowIndex = computed(() => nowIndexOf(points.value, now.value.getTime()))
// La ligne est dessinée par un plugin : Chart.js ne la redessine que si on le lui demande
const chart = useTemplateRef<{ chart?: ChartJS<'line'> }>('chart')
watch(nowIndex, () => chart.value?.chart?.update('none'))

// Pic prévu : à son heure et à sa valeur, celle du texte sous le graphique (maximum de
// l'heure quand le modèle le donne, donc au-dessus de la courbe moyenne)
const peak = computed(() => peakOnAxis(points.value, props.series))

// Heure de Paris, quel que soit le fuseau du poste
const labels = computed(() => points.value.map((p) => formatAxisHour(p.t)))

const data = computed<ChartData<'line'>>(() => {
  const peakPoint = peak.value
  return {
    labels: labels.value,
    datasets: [
      {
        label: 'Fourchette basse',
        data: points.value.map((p) => p.basse),
        borderWidth: 0,
        pointRadius: 0,
        // Comme la courbe prévue : la bande traverse l'heure en cours, laissée vide
        spanGaps: true,
      },
      {
        label: 'Fourchette haute',
        data: points.value.map((p) => p.haute),
        borderWidth: 0,
        pointRadius: 0,
        spanGaps: true,
        backgroundColor: colors.value.band,
        fill: '-1', // remplit jusqu'à la fourchette basse
      },
      {
        label: 'Mesures réelles',
        data: points.value.map((p) => p.mesure),
        borderColor: colors.value.ink,
        borderWidth: 2,
        pointRadius: points.value.map((p) => (isImputed(p) ? 3 : 0)),
        pointBorderWidth: 1.5,
        pointBackgroundColor: 'transparent',
        pointBorderColor: colors.value.ink,
        tension: 0.2,
        spanGaps: false,
      },
      {
        label: 'Prédiction',
        data: points.value.map((p) => p.pred),
        borderColor: colors.value.ink,
        borderWidth: 2,
        borderDash: [6, 5],
        spanGaps: true,
        tension: 0.35,
        pointRadius: 0,
      },
      {
        label: `${props.seuilPct ?? 90} % de la capacité`,
        data: points.value.map(() => seuil.value),
        borderColor: colors.value.muted,
        borderWidth: 1,
        borderDash: [4, 4],
        pointRadius: 0,
      },
      {
        // Rond du pic prévu, seul point de ce jeu de données
        label: 'Pic prévu',
        data: points.value.map((_, i) =>
          peakPoint && i === peakPoint.index ? peakPoint.kw : null,
        ),
        showLine: false,
        pointRadius: 6,
        pointBorderWidth: 2,
        pointBackgroundColor: 'transparent',
        pointBorderColor: colors.value.ink,
      },
    ],
  }
})

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

// Sur un écran étroit, 8 dates (« jeu. 14 h ») ne tiennent pas sans se chevaucher
const wide = useMediaQuery('(min-width: 640px)')

const options = computed<ChartOptions<'line'>>(() => ({
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  scales: {
    x: {
      grid: { display: false },
      ticks: { maxTicksLimit: wide.value ? 8 : 4, color: colors.value.muted, maxRotation: 0 },
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
      // Pas de ligne « Prédiction » sur le point de jonction : c'est la dernière mesure
      // Ni le rond du pic (5) : l'infobulle de la prédiction donne déjà le maximum de l'heure
      filter: (item) =>
        item.raw !== null &&
        item.datasetIndex >= 2 &&
        item.datasetIndex !== 5 &&
        !(item.datasetIndex === 3 && points.value[item.dataIndex]?.mesure !== null),
      callbacks: {
        label: (item) => {
          const point = points.value[item.dataIndex]
          // Heure prévue : moyenne, fourchette et maximum de l'heure quand ils existent
          if (item.datasetIndex === 3 && point) {
            const lignes = [`Prédiction : ${formatKw(Number(item.raw))} en moyenne`]
            if (point.basse !== null && point.haute !== null) {
              lignes.push(`fourchette : ${formatKw(point.basse)} – ${formatKw(point.haute)}`)
            }
            if (point.pic !== null) lignes.push(`maximum de l'heure : ${formatKw(point.pic)}`)
            return lignes
          }
          // Heure réelle : kWh et euros. Le tracé reste en kW (les kWh d'une heure).
          if (item.datasetIndex === 2 && point?.kwh != null) {
            const cout = point.cout == null ? '' : ` · ${formatEurCents(point.cout)}`
            const lignes = [`Consommation : ${formatKwh(point.kwh)}${cout}`]
            if (point.imputees > 0) {
              lignes.push(`dont ${point.imputees} min reconstituées après une panne`)
            }
            return lignes
          }
          return `${item.dataset.label} : ${formatKw(Number(item.raw))}`
        },
      },
    },
  },
}))
</script>

<template>
  <div>
    <div class="h-72 sm:h-80">
      <Line ref="chart" :data="data" :options="options" :plugins="[nowLine]" />
    </div>
    <ul class="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted-foreground">
      <li class="flex items-center gap-2">
        <span class="h-0.5 w-5 bg-foreground" aria-hidden="true" /> mesures réelles
      </li>
      <li v-if="series.predictions.length" class="flex items-center gap-2">
        <span class="w-5 border-t-2 border-dashed border-foreground" aria-hidden="true" />
        prédiction
      </li>
      <li v-if="hasBand" class="flex items-center gap-2">
        <span class="h-3 w-5 rounded-sm bg-(--chart-canvas-band)" aria-hidden="true" /> fourchette
        (valeur basse – valeur haute)
      </li>
      <li v-if="peak" class="flex items-center gap-2">
        <span class="mx-1 size-3 rounded-full border-2 border-foreground" aria-hidden="true" />
        pic prévu
      </li>
      <li v-if="hasImputed" class="flex items-center gap-2">
        <span
          class="mx-1.5 size-2 rounded-full border-[1.5px] border-foreground"
          aria-hidden="true"
        />
        heure en partie reconstituée après une panne
      </li>
    </ul>
  </div>
</template>
