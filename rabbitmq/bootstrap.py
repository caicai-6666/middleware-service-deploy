"""容器启动后声明业务流，完成后才允许健康检查通过。"""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


READY = Path("/tmp/middleware-streams-ready")
STREAM_DEFAULTS = {
    "RABBITMQ_REQUEST_STREAM": "ingestion-requests",
    "RABBITMQ_RESULT_STREAM": "ingestion-results",
    "RABBITMQ_DELETION_REQUEST_STREAM": "deletion-requests",
    "RABBITMQ_DELETION_RESULT_STREAM": "deletion-results",
}


def stream_definitions(environment):
    vhost = environment.get("RABBITMQ_DEFAULT_VHOST", "/")
    if not isinstance(vhost, str) or not vhost.strip():
        raise ValueError("RABBITMQ_DEFAULT_VHOST 必须为非空字符串")
    names = [environment.get(key, default) for key, default in STREAM_DEFAULTS.items()]
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError("四个业务流名称必须为非空字符串")
    if len(set(names)) != len(names):
        raise ValueError("四个业务流名称不能相同")
    # 在节点默认账号/vhost 初始化之后导入，只声明队列，不导入或修改用户与权限。
    return {"queues": [
        {"name": name, "vhost": vhost, "durable": True, "auto_delete": False,
         "arguments": {"x-queue-type": "stream"}}
        for name in names
    ]}


class ShutdownRequested(Exception):
    def __init__(self, signum):
        self.signum = signum


def stop_server(server):
    if server.poll() is not None:
        return
    # Python 是 PID 1，需要转发停止信号并回收 broker；超时才强制终止。
    try:
        os.killpg(server.pid, signal.SIGTERM)
    except ProcessLookupError:
        server.wait()
        return
    try:
        server.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(server.pid, signal.SIGKILL)
        server.wait()


def wait_for_startup(server, cli):
    # 节点尚未注册到 epmd 时，await_startup 也可能立即返回连接错误，需在总期限内重试。
    deadline = time.monotonic() + 120
    last_error = ""
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError("RabbitMQ 节点在初始化完成前退出")
        try:
            result = subprocess.run([*cli, "-q", "--timeout", "5", "await_startup"],
                                    capture_output=True, text=True, timeout=min(10, deadline - time.monotonic()))
            if result.returncode == 0:
                return
            last_error = result.stderr.strip()
        except subprocess.TimeoutExpired:
            last_error = "await_startup 超时"
        time.sleep(1)
    raise RuntimeError(f"RabbitMQ 节点启动超时：{last_error}")


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    arguments = arguments or ["rabbitmq-server"]
    if arguments[0] != "rabbitmq-server":
        # 保留官方镜像执行 CLI 或临时诊断命令的用法。
        os.execvp("docker-entrypoint.sh", ["docker-entrypoint.sh", *arguments])
    READY.unlink(missing_ok=True)
    definitions = stream_definitions(os.environ)
    server = None
    definition_path = None

    def request_shutdown(signum, frame):
        raise ShutdownRequested(signum)

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, request_shutdown)
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as output:
            definition_path = Path(output.name)
            json.dump(definitions, output, ensure_ascii=False)
        # 文件只有流定义，不包含凭据；rabbitmq 用户执行 CLI 时需要读取它。
        definition_path.chmod(0o644)
        server = subprocess.Popen(["docker-entrypoint.sh", *arguments], start_new_session=True)
        cli = ["gosu", "rabbitmq", "rabbitmqctl"] if os.getuid() == 0 else ["rabbitmqctl"]
        wait_for_startup(server, cli)
        subprocess.run([*cli, "-q", "--timeout", "30", "import_definitions", str(definition_path)],
                       check=True, timeout=35)
        # 导入完成后复核实际队列，避免同名非 Stream 队列被当成已初始化。
        vhost = definitions["queues"][0]["vhost"]
        actual = json.loads(subprocess.check_output(
            [*cli, "-q", "--timeout", "30", "list_queues", "-p", vhost,
             "name", "type", "durable", "auto_delete", "--formatter=json"], timeout=35, text=True))
        by_name = {queue["name"]: queue for queue in actual}
        for expected in definitions["queues"]:
            queue = by_name.get(expected["name"], {})
            if queue.get("type") != "stream" or queue.get("durable") is not True or queue.get("auto_delete") is not False:
                raise RuntimeError(f"业务流不存在或声明不兼容：{expected['name']}")
        READY.touch()
        print("四个业务流初始化完成，已有消息和消费进度保留", flush=True)
        return server.wait()
    except ShutdownRequested as error:
        return 128 + error.signum
    except Exception as error:
        print(f"RabbitMQ 业务流初始化失败：{error}", file=sys.stderr, flush=True)
        return 1
    finally:
        READY.unlink(missing_ok=True)
        # 清理时不再抛信号异常，保证服务器进程和临时定义文件得到回收。
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if server is not None:
            stop_server(server)
        if definition_path is not None:
            definition_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
