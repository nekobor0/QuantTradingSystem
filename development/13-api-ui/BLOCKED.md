# api_ui 待补决清单

- FastAPI/Pydantic/Streamlit 当前环境可用但 pyproject 未声明；为保护前序冻结指纹本模块不改 manifest，第 14 模块必须补齐/锁定发布依赖并验证干净安装。
- 真实 PostgreSQL 不可用；用 SQLite 验证仓储契约并交付 PostgreSQL DDL，live 验收留第 14 模块。
- 生产身份源、密码策略和 TLS/反向代理尚未提供；模块使用注入式 CredentialVerifier 与服务端 session 契约，不硬编码生产密码。
