# instruments 待裁决清单

- 真实 PostgreSQL 集成测试暂不可运行：本机无 psql/psycopg，Docker daemon 未启动。当前使用 SQLite 仓储契约测试与 PostgreSQL DDL/编译测试；需在 platform_operations 提供数据库后补跑真实连接验收。
