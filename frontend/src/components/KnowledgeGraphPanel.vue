<script setup lang="ts">
import { computed } from "vue";

import EmptyState from "@/components/EmptyState.vue";

export interface GraphNode {
  id: number;
  name: string;
  type: string;
}

export interface GraphEdge {
  id: number;
  source: number;
  target: number;
  type: string;
}

const props = defineProps<{
  nodes: GraphNode[];
  edges: GraphEdge[];
}>();

const WIDTH = 720;
const HEIGHT = 380;
const RADIUS = 126;
const COLORS = ["#e8a33d", "#4fd1b0", "#6aa9ff", "#ef6a5b", "#b49bff"];

const display = computed(() => {
  const list = props.nodes.slice(0, 18);
  const positions = new Map<number, { x: number; y: number }>();
  const cx = WIDTH / 2;
  const cy = HEIGHT / 2;

  list.forEach((node, index) => {
    const angle = (index / list.length) * Math.PI * 2 - Math.PI / 2;
    positions.set(node.id, {
      x: cx + Math.cos(angle) * RADIUS,
      y: cy + Math.sin(angle) * RADIUS,
    });
  });

  const typeColor = new Map<string, string>();
  const nodes = list.map((node) => {
    if (!typeColor.has(node.type)) {
      typeColor.set(node.type, COLORS[typeColor.size % COLORS.length]);
    }
    const point = positions.get(node.id) ?? { x: cx, y: cy };
    return {
      id: node.id,
      x: point.x,
      y: point.y,
      color: typeColor.get(node.type) || COLORS[0],
      label: String(node.name).slice(0, 12),
      type: node.type,
    };
  });

  const edges = props.edges
    .filter((edge) => positions.has(edge.source) && positions.has(edge.target))
    .map((edge) => {
      const source = positions.get(edge.source)!;
      const target = positions.get(edge.target)!;
      return {
        id: edge.id,
        x1: source.x,
        y1: source.y,
        x2: target.x,
        y2: target.y,
        labelX: (source.x + target.x) / 2,
        labelY: (source.y + target.y) / 2 - 5,
        type: edge.type,
      };
    });

  return { nodes, edges };
});
</script>

<template>
  <EmptyState
    v-if="!nodes.length"
    text="还没有实体与关系，导入三元组后这里会出现图谱。"
  />
  <div v-else class="graph-box">
    <svg :viewBox="`0 0 ${WIDTH} ${HEIGHT}`" width="100%">
      <g>
        <line
          v-for="edge in display.edges"
          :key="`edge-${edge.id}`"
          :x1="edge.x1"
          :y1="edge.y1"
          :x2="edge.x2"
          :y2="edge.y2"
          stroke="rgba(151,178,204,.2)"
          stroke-width="1.2"
        />
        <text
          v-for="edge in display.edges"
          :key="`edge-label-${edge.id}`"
          :x="edge.labelX"
          :y="edge.labelY"
          text-anchor="middle"
          fill="#5d6e80"
          font-size="9"
        >
          {{ edge.type }}
        </text>
      </g>
      <g v-for="node in display.nodes" :key="`node-${node.id}`">
        <circle
          :cx="node.x"
          :cy="node.y"
          r="20"
          fill="rgba(7,10,15,.92)"
          :stroke="node.color"
          stroke-width="1.5"
        />
        <circle :cx="node.x" :cy="node.y" r="3.5" :fill="node.color" />
        <text
          :x="node.x"
          :y="node.y + 34"
          text-anchor="middle"
          fill="#c3d0dc"
          font-size="10"
        >
          {{ node.label }}
        </text>
        <text
          :x="node.x"
          :y="node.y + 47"
          text-anchor="middle"
          fill="#5d6e80"
          font-size="8"
        >
          {{ node.type }}
        </text>
      </g>
    </svg>
  </div>
</template>
