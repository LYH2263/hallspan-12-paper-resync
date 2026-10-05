# HallSpan 考场间距排座

在考室网格上按最小曼哈顿距离排座，同试卷套不得四邻相邻，并输出违规与统计。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4900 |
| API | http://localhost:9900 |
| API 文档 | http://localhost:9900/docs |
| Postgres | localhost:5450 |

健康检查：`GET http://localhost:9900/api/health`

## 使用说明

1. 在「考室」「考生」「试卷套」确认基础数据。
2. 打开「排座图」执行间距排座。
3. 在「违规」查看间距或同卷相邻问题。
4. 在「统计」查看占用与违规汇总。

## 更换考生试卷套

`PUT /api/candidates/{id}/paper`，请求体 `{"paper_id": <套别ID>}`。

- 与该室当前有效方案原子提交：套别字段、最新排座图、违规/未排列表一起成功或一起失败。
- 该室已有有效方案时，按新套别同事务重算邻接与未排，追加新的方案快照；历史方案保持不动。
- 套别不存在则拒绝（404），名册、排座图、统计全部停在拒绝前。
- 该室尚无方案时仅更新套别字段，不凭空生成方案。

## 开发与测试

```bash
docker compose exec api pytest -q
```
