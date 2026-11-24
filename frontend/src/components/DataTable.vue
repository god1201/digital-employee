<script setup lang="ts">
export interface TableColumn {
  key?: string;
  label: string;
  format?: (row: any) => string;
}

withDefaults(
  defineProps<{
    columns: TableColumn[];
    rows: any[];
    emptyText?: string;
  }>(),
  { emptyText: "暂无数据" },
);
</script>

<template>
  <div v-if="!rows.length" class="empty">{{ emptyText }}</div>
  <div v-else class="table-wrap">
    <table>
      <thead>
        <tr>
          <th v-for="column in columns" :key="column.label">{{ column.label }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, index) in rows" :key="row?.id ?? index">
          <td v-for="column in columns" :key="column.label">
            <slot :name="`cell-${column.key || column.label}`" :row="row">
              <span v-if="column.format" v-html="column.format(row)" />
              <span v-else>{{ column.key ? row[column.key] ?? "—" : "" }}</span>
            </slot>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
