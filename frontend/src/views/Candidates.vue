<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
interface Cand { id: number; hall_id: number; name: string; ticket_no: string; paper_id: number }
interface Paper { id: number; code: string; title: string }
const rows = ref<Cand[]>([])
const papers = ref<Paper[]>([])
const saving = ref<Set<number>>(new Set())
const okMsg = ref<Record<number, string>>({})
const errMsg = ref<Record<number, string>>({})

onMounted(async () => {
  const [c, p] = await Promise.all([api<Cand[]>('/candidates'), api<Paper[]>('/papers')])
  rows.value = c
  papers.value = p
})
function paperCode(id: number) {
  return papers.value.find(p => p.id === id)?.code ?? `卷${id}`
}
async function save(r: Cand, ev: Event) {
  const paper_id = Number((ev.target as HTMLSelectElement).value)
  if (paper_id === r.paper_id) return
  saving.value.add(r.id)
  errMsg.value[r.id] = ''
  okMsg.value[r.id] = ''
  const prev = r.paper_id
  try {
    const res = await api<{ recomputed: boolean }>(`/candidates/${r.id}/paper`, {
      method: 'PUT',
      body: JSON.stringify({ paper_id }),
    })
    // 仅在后端事务成功后才更新本地字段，保证名单与有效方案同源
    r.paper_id = paper_id
    okMsg.value[r.id] = res.recomputed ? '已保存，有效方案连同邻接与未排重算' : '已保存'
  } catch (e) {
    // 拒绝/回滚：下拉恢复旧套别，名单停在拒绝前
    ;(ev.target as HTMLSelectElement).value = String(prev)
    errMsg.value[r.id] = '保存失败，已保持原方案：' + (e instanceof Error ? e.message : String(e))
  } finally {
    saving.value.delete(r.id)
  }
}
</script>
<template>
  <h1>考生名册</h1>
  <p class="sub">更换试卷套将与该室当前有效方案一起成功或一起失败</p>
  <div class="hs-clipboard" style="max-width:560px">
    <h2>考生名册 · Clipboard</h2>
    <div v-for="r in rows" :key="r.id" class="hs-roster-row" style="flex-wrap:wrap;gap:.4rem">
      <div>
        <div>{{ r.name }}</div>
        <div class="hs-ticket">{{ r.ticket_no }}</div>
      </div>
      <div style="margin-left:auto;display:flex;flex-direction:column;align-items:flex-end;gap:.2rem">
        <label style="font-size:.8rem">
          试卷套
          <select :value="r.paper_id" :disabled="saving.has(r.id)" @change="save(r, $event)">
            <option v-for="p in papers" :key="p.id" :value="p.id">{{ p.code }} · {{ p.title }}</option>
          </select>
        </label>
        <small v-if="okMsg[r.id]" style="color:#1a7f37">{{ okMsg[r.id] }}</small>
        <small v-if="errMsg[r.id]" style="color:#b42318">{{ errMsg[r.id] }}</small>
        <small class="muted">室{{ r.hall_id }} · 当前 {{ paperCode(r.paper_id) }}</small>
      </div>
    </div>
  </div>
</template>
