<script setup lang="ts">
import { computed } from "vue";

interface Point {
  date: string;
  success_rate: number;
  takeover_rate: number;
}

const props = defineProps<{ series: Point[] }>();

const width = 720;
const height = 200;
const pad = { l: 42, r: 16, t: 14, b: 26 };
const innerW = width - pad.l - pad.r;
const innerH = height - pad.t - pad.b;

function ratio(value: number): number {
  return Math.max(0, Math.min(1, Number(value || 0)));
}

const x = (index: number) =>
  pad.l +
  (props.series.length <= 1 ? innerW / 2 : (index / (props.series.length - 1)) * innerW);
const y = (value: number) => pad.t + innerH - ratio(value) * innerH;

function pathOf(key: "success_rate" | "takeover_rate"): string {
  return props.series
    .map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point[key]).toFixed(1)}`)
    .join(" ");
}

const successPath = computed(() => pathOf("success_rate"));
const takeoverPath = computed(() => pathOf("takeover_rate"));
const labelEvery = computed(() =>
  Math.max(1, Math.ceil(props.series.length / 7)),
);
const grid = [0, 0.5, 1].map((value) => ({ value, y: y(value) }));
</script>

<template>
  <div class="rate-curve">
    <div class="legend">
      <span><i class="dot success"></i>成功率</span>
      <span><i class="dot takeover"></i>接管率</span>
    </div>
    <svg :viewBox="`0 0 ${width} ${height}`" role="img" aria-label="学习曲线">
      <g v-for="line in grid" :key="line.value">
        <line
          :x1="pad.l"
          :y1="line.y"
          :x2="width - pad.r"
          :y2="line.y"
          stroke="rgba(151,178,204,.09)"
          stroke-dasharray="3 5"
        />
        <text
          :x="pad.l - 9"
          :y="line.y + 3"
          text-anchor="end"
          fill="#5d6e80"
          font-size="9"
        >
          {{ Math.round(line.value * 100) }}%
        </text>
      </g>
      <path :d="takeoverPath" fill="none" stroke="#ef6a5b" stroke-width="1.8" stroke-dasharray="4 4" />
      <path :d="successPath" fill="none" stroke="#4fd1b0" stroke-width="2" />
      <g v-for="(point, index) in series" :key="point.date">
        <circle :cx="x(index)" :cy="y(point.success_rate)" r="2.2" fill="#4fd1b0" />
        <circle :cx="x(index)" :cy="y(point.takeover_rate)" r="2" fill="#ef6a5b" />
        <text
          v-if="index % labelEvery === 0 || index === series.length - 1"
          :x="x(index)"
          :y="height - 8"
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

<style scoped>
.rate-curve {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel-2);
  padding: 8px 10px 2px;
}
.legend {
  display: flex;
  gap: 14px;
  font-size: 10.5px;
  color: var(--dim);
  padding: 2px 4px 0;
}
.legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
}
.dot.success {
  background: #4fd1b0;
}
.dot.takeover {
  background: #ef6a5b;
}
svg {
  width: 100%;
  height: auto;
  display: block;
}
</style>
