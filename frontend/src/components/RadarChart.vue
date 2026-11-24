<script setup lang="ts">
import { computed } from "vue";

interface Axis {
  key?: string;
  label: string;
  value: number;
}

const props = withDefaults(
  defineProps<{ axes: Axis[]; max?: number; size?: number }>(),
  { max: 1, size: 340 },
);

const count = computed(() => Math.max(1, props.axes.length));
const center = computed(() => props.size / 2);
const radius = computed(() => props.size / 2 - 56);

function angle(index: number): number {
  return -Math.PI / 2 + (index / count.value) * Math.PI * 2;
}

function ratio(value: number): number {
  const max = props.max || 1;
  return Math.max(0, Math.min(1, Number(value || 0) / max));
}

function point(index: number, value: number) {
  const r = radius.value * ratio(value);
  return {
    x: center.value + Math.cos(angle(index)) * r,
    y: center.value + Math.sin(angle(index)) * r,
  };
}

function ring(scale: number): string {
  return props.axes
    .map((_axis, index) => {
      const r = radius.value * scale;
      const x = center.value + Math.cos(angle(index)) * r;
      const y = center.value + Math.sin(angle(index)) * r;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

const polygon = computed(() =>
  props.axes
    .map((axis, index) => {
      const p = point(index, axis.value);
      return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    })
    .join(" "),
);

const labels = computed(() =>
  props.axes.map((axis, index) => {
    const r = radius.value + 22;
    const cos = Math.cos(angle(index));
    const sin = Math.sin(angle(index));
    return {
      label: axis.label,
      value: `${Math.round(ratio(axis.value) * 100)}%`,
      x: center.value + cos * r,
      y: center.value + sin * r,
      anchor: Math.abs(cos) < 0.2 ? "middle" : cos > 0 ? "start" : "end",
      dy: sin > 0.4 ? 10 : sin < -0.4 ? -4 : 4,
    };
  }),
);

const spokes = computed(() =>
  props.axes.map((_axis, index) => {
    const r = radius.value;
    return {
      x: center.value + Math.cos(angle(index)) * r,
      y: center.value + Math.sin(angle(index)) * r,
    };
  }),
);
</script>

<template>
  <div class="radar">
    <svg
      :viewBox="`0 0 ${size} ${size}`"
      role="img"
      aria-label="能力雷达"
    >
      <polygon
        v-for="scale in [0.25, 0.5, 0.75, 1]"
        :key="scale"
        :points="ring(scale)"
        fill="none"
        stroke="rgba(151,178,204,.16)"
        stroke-dasharray="3 5"
      />
      <line
        v-for="(spoke, index) in spokes"
        :key="`spoke-${index}`"
        :x1="center"
        :y1="center"
        :x2="spoke.x"
        :y2="spoke.y"
        stroke="rgba(151,178,204,.1)"
      />
      <polygon
        :points="polygon"
        fill="rgba(232,163,61,.18)"
        stroke="#e8a33d"
        stroke-width="2"
      />
      <circle
        v-for="(axis, index) in axes"
        :key="axis.key || index"
        :cx="point(index, axis.value).x"
        :cy="point(index, axis.value).y"
        r="3"
        fill="#e8a33d"
      />
      <g v-for="(item, index) in labels" :key="`label-${index}`">
        <text
          :x="item.x"
          :y="item.y + item.dy"
          :text-anchor="item.anchor"
          fill="#8b9bad"
          font-size="10"
        >
          {{ item.label }}
        </text>
        <text
          :x="item.x"
          :y="item.y + item.dy + 13"
          :text-anchor="item.anchor"
          fill="#e8a33d"
          font-size="10"
          font-family="var(--mono)"
        >
          {{ item.value }}
        </text>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.radar {
  display: flex;
  justify-content: center;
  padding: 6px 0 2px;
}
svg {
  width: 100%;
  max-width: 360px;
  height: auto;
}
</style>
