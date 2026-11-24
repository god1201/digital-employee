<script setup lang="ts">
import { computed } from "vue";

interface Point {
  date: string;
  total: number;
  succeeded: number;
  failed: number;
}

const props = defineProps<{ series: Point[] }>();

const width = 720;
const height = 240;
const pad = { l: 42, r: 16, t: 16, b: 28 };
const innerW = width - pad.l - pad.r;
const innerH = height - pad.t - pad.b;

const max = computed(() => Math.max(1, ...props.series.map((d) => Number(d.total || 0))));
const x = (i: number) =>
  pad.l + (props.series.length <= 1 ? innerW / 2 : (i / (props.series.length - 1)) * innerW);
const y = (v: number) => pad.t + innerH - (Number(v || 0) / max.value) * innerH;

const totalPath = computed(() =>
  props.series.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.total).toFixed(1)}`).join(" "),
);
const successPath = computed(() =>
  props.series
    .map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.succeeded).toFixed(1)}`)
    .join(" "),
);
const failPath = computed(() =>
  props.series
    .map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.failed).toFixed(1)}`)
    .join(" "),
);
const areaPath = computed(
  () =>
    `M${x(0)},${pad.t + innerH} ` +
    props.series.map((d, i) => `L${x(i)},${y(d.total)}`).join(" ") +
    ` L${x(props.series.length - 1)},${pad.t + innerH} Z`,
);
const grid = computed(() =>
  [0, 0.25, 0.5, 0.75, 1].map((p) => {
    const value = Math.round(max.value * p);
    return { value, y: y(value) };
  }),
);
</script>

<template>
  <div class="chart">
    <svg :viewBox="`0 0 ${width} ${height}`" role="img" aria-label="任务趋势">
      <defs>
        <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#e8a33d" stop-opacity=".32" />
          <stop offset="1" stop-color="#e8a33d" stop-opacity="0" />
        </linearGradient>
      </defs>
      <g v-for="line in grid" :key="line.value">
        <line
          :x1="pad.l"
          :y1="line.y"
          :x2="width - pad.r"
          :y2="line.y"
          stroke="rgba(151,178,204,.09)"
          stroke-dasharray="3 5"
        />
        <text :x="pad.l - 9" :y="line.y + 3" text-anchor="end" fill="#5d6e80" font-size="9">
          {{ line.value }}
        </text>
      </g>
      <path :d="areaPath" fill="url(#trendFill)" />
      <path :d="totalPath" fill="none" stroke="#e8a33d" stroke-width="2" />
      <path :d="successPath" fill="none" stroke="#4fd1b0" stroke-width="2" />
      <path :d="failPath" fill="none" stroke="#ef6a5b" stroke-width="2" stroke-dasharray="4 4" />
      <g v-for="(point, index) in series" :key="point.date">
        <circle :cx="x(index)" :cy="y(point.total)" r="2.4" fill="#e8a33d" />
        <text
          :x="x(index)"
          :y="height - 9"
          text-anchor="middle"
          fill="#5d6e80"
          font-size="9"
        >
          {{ String(point.date).slice(5) }}
        </text>
      </g>
    </svg>
  </div>
</template>
