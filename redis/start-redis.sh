#!/bin/sh
set -eu

# 缺少凭据时拒绝启动；密码作为单个参数传入，不拼接进配置或执行代码。
: "${REDIS_PASSWORD:?必须设置 REDIS_PASSWORD}"
exec docker-entrypoint.sh redis-server /usr/local/etc/redis/redis.conf \
    --requirepass "$REDIS_PASSWORD"
