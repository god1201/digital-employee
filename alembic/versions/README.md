# 数据库迁移

开发期可设置 `AUTO_CREATE_TABLES=true` 自动建表。

生产环境请关闭自动建表，并执行：

```bash
alembic revision --autogenerate -m "init schema"
alembic upgrade head
```
