FROM rabbitmq:4.3-management@sha256:8dd6e3570ddaa2ef82a6c3a8950e79c1f73893adfbdddbc374fc1f1ac8a0f5dd

# 初始化只使用 Python 标准库生成 JSON，不安装后端依赖。
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

COPY rabbitmq.conf enabled_plugins /etc/rabbitmq/
COPY bootstrap.py /usr/local/bin/middleware-rabbitmq-bootstrap.py

HEALTHCHECK --interval=10s --timeout=10s --start-period=30s --retries=12 \
    CMD test -f /tmp/middleware-streams-ready && rabbitmq-diagnostics -q check_running

ENTRYPOINT ["python3", "-u", "/usr/local/bin/middleware-rabbitmq-bootstrap.py"]
CMD ["rabbitmq-server"]
