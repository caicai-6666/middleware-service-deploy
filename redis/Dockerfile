FROM redis:7.4.8-bookworm@sha256:3e0669e42d4fe421c9dea0ba5fbc04d336b80b4f32a6c7d25bee3a1d089288a1

COPY redis.conf /usr/local/etc/redis/redis.conf
COPY start-redis.sh /usr/local/bin/middleware-start-redis.sh

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=6 \
    CMD REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --raw ping | grep -qx PONG

# 保留官方入口；脚本再次委托官方入口启动服务器，以沿用降权及卷权限处理。
CMD ["sh", "/usr/local/bin/middleware-start-redis.sh"]
