# 中间件服务部署

本仓库维护 middleware-service 后端、RabbitMQ Streams 和 Redis 的生产部署配置。后端代码独立管理，部署时拉取到本仓库的 `middleware-service/` 子目录；本机开发配置由后端工作区自行维护，不写入生产 Compose。

## 目录与职责

```text
middleware-service-deploy/
├── README.md
├── docker-compose.yml
├── .env.example                 # 统一部署参数模板
├── platform.yaml.example        # 平台身份与展示信息模板
├── rabbitmq/                    # 镜像、五流初始化、插件与广播地址
├── redis/                       # 镜像、认证入口、AOF 配置
└── middleware-service/          # 后端仓库，独立拉取与提交
```

实际 `.env`、`platform.yaml` 不进入版本控制。持久数据存放于 Docker 命名卷，不放入 Git；后端仓库中的 data 占位不是数据备份。接口和业务契约以 backend 仓库的 `description/api/readme.md` 为入口。

---

## 首次部署

1. 将后端仓库拉取到 `./middleware-service`，确认其中包含 Dockerfile、requirement.txt 和完整 app 源码。
2. 准备配置：

```bash
cp .env.example .env
cp platform.yaml.example platform.yaml
```

修改 `.env` 中 RabbitMQ 和 Redis 的密码；不要使用示例值。修改 platform.yaml 中每个平台的 secret，代号与密钥必须唯一。注册中心代码须与 `RABBITMQ_REGISTRY_PLATFORM_CODE` 一致，默认 registry。

platform.yaml 示例包含 registry、knowledge-accumulation 和 platform-a。knowledge-accumulation 用于用户总表、登录成功缓存及管理员总表接口；若使用用户登录功能，必须保留这个固定平台代码并设置独立密钥。registry 与 knowledge-accumulation 均可全量同步用户与管理员，单用户资料更新及管理员单条增删由 registry 操作，用户登录缓存写入仅 knowledge-accumulation 可操作。platform/list 返回全部配置平台及 supports_a2a（是否参与 A2A 协议）、is_sub_management_platform（是否为子管理平台）和 is_management_entry（是否为管理平台入口），三个标记独立、默认 false，按实际情况设置，不改变认证或业务权限。is_sub_management_platform=true 时必须填写非空 a2aresponsibility，说明后续 A2A 协作职责，例如“负责解答合同相关问题。”；其他平台默认空字符串，平台列表同步返回。升级前检查现有子管理平台已填写该字段，否则后端启动校验会失败。原 show_in_list 已移除，旧 platform.yaml 需删除该字段后再更新后端。

description 支持 Markdown 字符串，可用 YAML 的 `|` 保留换行；后端原样返回，展示由调用端渲染。密钥直接写在 YAML 中，不展开环境变量。

3. 在本仓库目录验证并启动：

```bash
docker compose config --quiet
docker compose up -d --build --wait
docker compose ps
curl http://127.0.0.1:8000/middleware-service/api/health
```

后端代码在 `/workspace`，使用 Python 3.12，单实例、单 worker，容器内部监听 8000。宿主机默认只绑定 `127.0.0.1:8000`，外部访问可由上层反向代理接入。平台 YAML 只读挂载到 `/data/platform-config/platform.yaml`；源文件缺失会拒绝挂载，不自动创建同名目录。

---

## 中间件与消息流

RabbitMQ 与 Redis 只通过 Compose 内部网络供后端访问，分别为 rabbitmq:5552、redis:6379，不发布宿主机端口。RabbitMQ 与后端统一注入账号密码及 vhost，Redis 与后端统一注入独立的 Redis 密码。

| 环境变量 | 默认流名称 | 生产方 | 消费方 |
| --- | --- | --- | --- |
| `RABBITMQ_REQUEST_STREAM` | `ingestion-requests` | 子平台 | registry |
| `RABBITMQ_RESULT_STREAM` | `ingestion-results` | registry | 目标子平台 |
| `RABBITMQ_DELETION_REQUEST_STREAM` | `deletion-requests` | 子平台 | registry |
| `RABBITMQ_DELETION_RESULT_STREAM` | `deletion-results` | registry | 目标子平台 |
| `RABBITMQ_FILE_PERMISSION_STREAM` | `file-permission-adjustments` | registry | 目标子平台 |

五个流名必须互不相同。RabbitMQ 容器每次启动幂等声明 durable、非自动删除的 Stream，保留已有流中的消息和 offset。初始化与回查完成后才通过健康检查；后端只检查流是否存在，不补建。

后端等待 RabbitMQ 与 Redis 健康后启动。运行期间 `/health` 只表示应用存活，不持续探测所有中间件；中间件故障时相关业务接口可能返回 503。

---

## 环境参数

全部可注入变量见 `.env.example`，Compose 只将 environment 中显式列出的参数传入容器。

| 参数 | 默认值或用途 |
| --- | --- |
| `PLATFORM_SESSION_TTL_SECONDS` | 平台会话 90 秒。 |
| `PLATFORM_HEARTBEAT_INTERVAL_SECONDS` | 建议心跳 30 秒，须小于会话有效期。 |
| `PLATFORM_SESSION_CLEANUP_INTERVAL_SECONDS` | 失活资源清理间隔 10 秒。 |
| `USER_CACHE_TTL_SECONDS` | 用户登录 TTL 90 秒，有效查询时续期。 |
| `ASSISTANT_TASK_MAX_PER_USER`、`ASSISTANT_TASK_LEASE_SECONDS`、`ASSISTANT_TASK_RECEIPT_TTL_SECONDS` | 每用户 1000 个任务、执行租约 300 秒、确认后幂等记录保留 86400 秒。 |
| `ASSISTANT_USER_MESSAGE_MERGE_MAX_MESSAGES`、`ASSISTANT_USER_MESSAGE_MERGE_MAX_BYTES`、`ASSISTANT_USER_MESSAGE_MERGE_INTERVAL_SECONDS` | 用户任务最多合并 20 条、65536 原文字节，相邻消息间隔不超过 30 秒。 |
| `ASSISTANT_TASK_MAX_FILES`、`ASSISTANT_TASK_MAX_FILE_BYTES` | 每条任务最多 10 个附件（合并后也计数），单个附件最多 20971520 字节。 |
| `RABBITMQ_USER`、`RABBITMQ_PASSWORD` | RabbitMQ 首次初始化账号与后端连接身份。 |
| `RABBITMQ_VHOST` | 默认 `/`，同步注入初始化与后端。 |
| `RABBITMQ_REGISTRY_PLATFORM_CODE` | 默认 registry，决定注册中心业务角色。 |
| `REDIS_PASSWORD` | Redis 与后端统一密码，必须非空。 |
| `REDIS_DB`、`REDIS_KEY_PREFIX`、`REDIS_MAX_CONNECTIONS` | 默认 0、middleware-service、20。 |
| `INGESTION_CACHE_*`、`REVIEW_CACHE_*`、`DELETION_CACHE_*`、`DELETION_REVIEW_CACHE_*`、`FILE_PERMISSION_CACHE_*` | 五类独立预取缓存，每个平台每流默认 100 条、4194304 字节原始负载。 |

用户资料、登录 token 映射、平台管理员和助理任务存储在 Redis。平台会话、消息预取与发布锁仍在单进程内存中，保持后端单实例。模板不注入尚未接入的 Stream 保留时间或容量预留参数。

---

## AI 个人助理任务

每个 userid 使用一个 Redis 优先级任务队列，不增加 RabbitMQ Stream，也不创建结果队列。接口契约见后端仓库的 [AI 个人助理任务接口](middleware-service/description/api/assistant-task.md)，实现与配置说明见[助理任务队列](middleware-service/description/capability/application/assistant-task.md)。

- 接口前缀为 `/middleware-service/api/assistant/tasks`，提供 POST publish、pull、ack 和 GET status；均使用平台 Bearer Token。目前所有已认证平台均可操作指定用户的任务，接入平台负责用户及来源的业务校验。
- 优先级依次为 reminder、user_message、assistant_message、heartbeat；同级按入队序号排列，执行中的任务不被抢占。过期租约在下次 pull 时恢复领取，外部业务动作需按 task_id 做幂等处理。
- 仅尚未领取的 user_message 可在配置间隔内合并，合并时间取最新原始消息的接收时间，正文只增加 Markdown 分隔线，原始消息与所属附件分别保留。assistant_message 每次独立入队，不参与合并。
- 新发布的 assistant_message 必须提供非空白、1～128 字符的 source_assistant_id，JSON 与 multipart 均适用，缺失或无效返回 422；其他类型可省略。该字段用于标识发送方助理，不由目标 userid 推断。历史无来源任务仍可 pull/ack；重试时不能通过补填来源覆盖旧发布记录。
- status 返回当前是否有租约有效的任务，以及上次成功 ack 心跳任务的时间；仅发布或领取心跳不会更新时间，也不会自动续期平台或用户登录。心跳由生产端定期发布。

助理任务元数据由 redis-data 持久化，附件由 assistant-files 持久化；确认完成后才删除附件。给用户的结果由执行平台直接发送，给其他助理的消息重新 publish，业务动作完成后再 ack 原任务。

---

## 升级与配置变更

分别更新 deploy 与后端仓库，核对已有 `.env` 和 platform.yaml。已有部署补充 REDIS_PASSWORD，不覆盖原凭据，不用示例文件覆盖实际配置。

增加新流或变更 RabbitMQ 初始化脚本时，先启动中间件，再更新后端：

```bash
docker compose build rabbitmq redis backend
docker compose up -d --wait rabbitmq redis
docker compose up -d --wait backend
```

平台 YAML 在后端启动时加载一次；修改后执行 `docker compose restart backend`。修改 `.env` 后执行 `docker compose up -d --wait` 以重建受影响容器，单纯 restart 不会重新注入环境变量。后端重启会让平台访问令牌失效，各平台需重新登录；Redis 中未过期的用户登录状态与 RabbitMQ 消费进度保留。

RabbitMQ 默认账号与 vhost 仅在空卷首次初始化。已有卷修改 `.env` 不会更改 broker 内的现有账号密码或创建新 vhost，需先完成对应账号与权限维护。Redis 密码由启动时环境配置；轮换时同步重建 Redis 与后端容器。更改流名不会迁移原消息或 offset。

用户登录缓存新契约要求 knowledge-accumulation 通过 PUT /middleware-service/api/user/login-cache 写入 userid 和用户 access_token。其他平台 POST 同一路径时用用户 access_token 查询，平台认证仍由请求头 Bearer token 完成；旧值为 1 的登录记录不会被视为新的有效 token 登录，需在用户成功登录后重新写入。

---

## 持久化与运维

| 命名卷 | 挂载位置 | 内容 |
| --- | --- | --- |
| `rabbitmq-data` | `/var/lib/rabbitmq` | 流消息、offset 与 broker 数据。 |
| `redis-data` | `/data` | Redis AOF 数据。 |
| `backend-files` | `/workspace/data/ingestion-request/file` | 待入库请求附件，registry ack 后清理。 |
| `deletion-files` | `/workspace/data/deletion-request/file` | 兼容历史带附件删除申请；新删除申请不上传文件。 |
| `assistant-files` | `/workspace/data/assistant-task/file` | 助理任务临时附件，任务 ack 成功后清理，清理失败可重试相同 ack。 |

Redis 使用 AOF everysec、无周期 RDB，异常断电不保证零丢失。当前两个中间件均为单节点，不提供高可用；持久卷不能替代备份。不要通过 `docker compose down -v` 更新配置，它会删除持久卷中的业务数据。

```bash
docker compose logs --tail=100 backend rabbitmq redis
docker compose exec redis sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli ping'
docker compose exec rabbitmq rabbitmq-diagnostics -q check_running
```

停止容器可使用 `docker compose stop`，保留命名卷。备份和恢复时需同时考虑 RabbitMQ 消息引用的入库附件，以及 Redis 助理任务与 assistant-files 卷，保持消息、消费状态和文件的一致性。

助理任务 publish 兼容纯文本 JSON 与 multipart 多附件请求，文件显式传递后缀；合并时在各条原始用户消息中保留所属附件。文件由已认证平台通过 GET /middleware-service/api/resource/assistant-tasks/{file_id}?file_extension=pdf 下载，审核附件仍只允许 registry 读取。新增该功能后需重建后端镜像并执行 docker compose up -d --wait backend，使新增 assistant-files 卷及参数注入生效；不需要变更 RabbitMQ 流。已有容器文件系统中若已存有助理文件，应在挂载新卷前迁移，避免新卷遮蔽旧路径。


---

## 提交前验证记录

2026-10-22 从两个仓库当前 Git 提交候选范围导出独立快照，未复制实际 .env、platform.yaml、tests、scripts 或 data 中的本机配置。完成三镜像构建、pip check、独立 Compose 首次启动、三服务健康、五流初始化、平台登录、用户 token 写入及姓名查询、registry 管理员总表同步，以及文件权限调整 publish/pull/ack 验证。

验证使用随机凭据、独立项目名、临时端口和新命名卷。结束后已删除本次测试容器、网络和卷，未修改既有部署或业务数据。后端本机 217 项回归测试通过；测试源码按后端白名单策略不提交。
