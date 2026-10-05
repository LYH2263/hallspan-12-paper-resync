<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const papers = ref<any[]>([])
const error = ref('')
const saving = ref<number | null>(null)
async function load() {
  rows.value = await api('/candidates')
  papers.value = await api('/papers')
}
onMounted(load)
async function changePaper(c: any, ev: Event) {
  const pid = Number((ev.target as HTMLSelectElement).value)
  if (pid === c.paper_id) return
  error.value = ''
  saving.value = c.id
  try {
    // 后端原子提交：套别字段与该室最新排座图、违规/未排一起更新
    await api(`/candidates/${c.id}/paper`, { method: 'PUT', body: JSON.stringify({ paper_id: pid }) })
    await load()
  } catch (e: any) {
    // 拒绝或失败时名册停在原状，重新拉取以下拉回显
    error.value = `保存失败：${e.message}`
    await load()
  } finally {
    saving.value = null
  }
}
</script>
<template>
  <h1>考生名册</h1>
  <p class="sub">夹板名册样式 · 更换试卷套将连同该室有效方案原子重排</p>
  <p v-if="error" class="hs-error">{{ error }}</p>
  <div class="hs-clipboard" style="max-width:420px">
    <h2>考生名册 · Clipboard</h2>
    <div v-for="r in rows" :key="r.id ?? JSON.stringify(r)" class="hs-roster-row">
      <div>
        <div>{{ r.name }}</div>
        <div class="hs-ticket">{{ r.ticket_no }}</div>
      </div>
      <div>
        <select
          :value="r.paper_id"
          :disabled="saving === r.id"
          @change="changePaper(r, $event)"
        >
          <option v-for="p in papers" :key="p.id" :value="p.id">{{ p.code }}</option>
        </select>
        · 室{{ r.hall_id }}
      </div>
    </div>
  </div>
</template>
