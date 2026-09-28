"""macOS daily launcher. OS integration stays outside the model client."""
from __future__ import annotations

import argparse
import fcntl
import getpass
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

import yaml

from .storage import ROOT, read_yaml, write_yaml

DEFAULT_DATA = Path.home() / "Library" / "Application Support" / "ResumeProduce"
DATA_NAMES = ("data", "sources", "outputs", "applications.csv")


def data_directory(value=None):
    return Path(value or os.environ.get("RESUME_DATA_DIR") or DEFAULT_DATA).expanduser().resolve()


def initialize(destination: Path, source: Path = None):
    """Explicit, non-destructive copy; never initialize over existing data."""
    destination = destination.resolve()
    if destination.exists():
        raise ValueError(f"目标已存在，未修改任何资料：{destination}。已有资料请直接启动；恢复或迁移请选择新的空目录路径。")
    config = read_yaml(ROOT / "config.example.yaml", {})
    config["llm"]["mode"] = "live"
    if source is not None:
        source = source.expanduser().resolve()
        if not (source / "data" / "profile.yaml").is_file():
            raise ValueError("来源目录必须包含 data/profile.yaml。")
        if source == destination or source in destination.parents:
            raise ValueError("目标必须位于来源目录之外。")
        original = read_yaml(source / "config.yaml", {})
        # Copy only known non-secret configuration, never arbitrary old fields.
        for section, keys in (("llm", ("mode", "base_url", "model", "timeout_seconds", "max_tokens", "provider", "thinking")), ("app", ("port",))):
            values = original.get(section, {})
            for key in keys:
                if key in values:
                    config.setdefault(section, {})[key] = values[key]
    config["app"].update(host="127.0.0.1", debug=False)
    destination.mkdir(parents=True, mode=0o700)
    try:
        if source is not None:
            for name in DATA_NAMES:
                src, dst = source / name, destination / name
                if src.is_dir():
                    shutil.copytree(src, dst)
                elif src.is_file():
                    shutil.copy2(src, dst)
        else:
            write_yaml(destination / "data/profile.yaml", {"profile": {"name": "", "phone": "", "email": "", "photo_path": ""}, "education": []})
            write_yaml(destination / "data/skills.yaml", {"skills": []})
        for folder in ("data/experiences", "sources", "outputs"):
            (destination / folder).mkdir(parents=True, exist_ok=True)
        write_yaml(destination / "config.yaml", config)
    except Exception:
        # Only remove the new destination created by this invocation.
        shutil.rmtree(destination)
        raise


@contextmanager
def single_instance(directory: Path):
    """A stable inode lock also rejects same-data starts on different ports."""
    with (directory / ".resume.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("这份数据已有服务正在运行。请使用原窗口，或先停止原服务；不会启动第二份服务。") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    # Never unlink: a waiter must keep using the same inode.


def check_configuration(directory: Path):
    from .skill import ResumeSkill
    config_file = directory / "config.yaml"
    if not config_file.is_file() or not (directory / "data/profile.yaml").is_file():
        raise ValueError(f"数据目录尚未初始化：{directory}。请先运行初始化.command。")
    config = read_yaml(config_file, {})
    if not isinstance(config, dict) or not isinstance(config.get("llm"), dict) or not isinstance(config.get("app", {}), dict):
        raise ValueError("config.yaml 的 llm 和 app 必须是配置对象。")
    ResumeSkill(config, None)  # validates mode without reading a key or calling the API
    settings = config.get("app", {})
    if settings.get("host", "127.0.0.1") != "127.0.0.1" or settings.get("debug", False):
        raise ValueError("日常入口要求 app.host 为 127.0.0.1 且 app.debug 为 false。")
    port = settings.get("port", 5000)
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError("app.port 必须是 1024–65535 之间的整数；不会自动换端口。")
    for name in ("timeout_seconds", "max_tokens"):
        value = config["llm"].get(name, 90 if name == "timeout_seconds" else 8192)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"llm.{name} 必须是正整数。")
    return config, port


def check_writable(directory: Path):
    for name in ("", "data", "data/experiences", "sources", "outputs"):
        folder = directory / name
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=folder) as handle:
            handle.write(b"write-check")
            handle.flush()


def load_key(provider="deepseek"):
    from .models import PROVIDERS, key_available
    from .keychain import read_key
    if key_available(provider):
        return True
    try:
        key = read_key(provider)
        if key:
            os.environ[PROVIDERS[provider]["env"]] = key
            return True
    except (OSError, RuntimeError):
        print(f"无法读取 {PROVIDERS[provider]['name']} 钥匙串，请配置后重启。", flush=True)
    return False


def open_in_chrome(url):
    result = subprocess.run(
        ["open", "-a", "Google Chrome", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def existing_service(directory, port):
    import requests
    with requests.Session() as session:
        session.trust_env = False
        try:
            response = session.get(f"http://127.0.0.1:{port}/_local/ready", timeout=1)
        except requests.ConnectionError:
            return False
        except requests.RequestException as exc:
            raise ValueError("已有端口未响应，无法确认服务身份。") from exc
    try:
        identity = response.json()
    except ValueError:
        identity = {}
    if not response.ok or identity != {"application": "resume-produce", "data_directory": str(directory.resolve())}:
        raise ValueError("端口已被其他服务或不同数据实例使用，未打开页面。")
    return True


def open_existing(directory):
    _, port = check_configuration(directory)
    if not existing_service(directory, port):
        raise ValueError("服务尚未就绪，请稍后再点击应用图标。")
    if not open_in_chrome(f"http://127.0.0.1:{port}"):
        raise ValueError("无法打开 Google Chrome，请检查安装。")


def serve(directory: Path, open_browser=True, use_keychain=True, reuse=False):
    from app import create_app
    from waitress import create_server
    config, port = check_configuration(directory)
    reusable = False
    if reuse:
        try:
            reusable = existing_service(directory, port)
        except ValueError:
            # macOS may expose a wildcard listener (AirPlay) while allowing
            # this app to bind its specific loopback address. Never open the
            # unknown service; let the actual bind decide port availability.
            pass
    if reusable:
        if open_browser:
            open_existing(directory)
        print("已打开现有服务；它由原启动入口管理，退出此应用不会停止它。", flush=True)
        return
    with single_instance(directory):
        check_writable(directory)
        if config["llm"]["mode"].strip().lower() == "live":
            from .models import PROVIDERS, selection, key_available
            if use_keychain:
                for provider in PROVIDERS:
                    load_key(provider)
            available = key_available(selection(config["llm"])["provider"])
            print("模型密钥已就绪（实际调用时验证有效性）。" if available else "未配置模型密钥；历史、续编、编辑、导出和打印仍可用。", flush=True)
        application = create_app(ROOT, data_root=directory)
        # Validate existing records before announcing readiness; no model call.
        application.extensions["resume_repository"].evidence_index()
        application.add_url_rule("/_local/ready", "local_ready", lambda: {"application": "resume-produce", "data_directory": str(directory.resolve())})
        try:
            server = create_server(application, host="127.0.0.1", port=port, threads=4)
        except OSError as exc:
            raise ValueError(f"无法使用本机端口 {port}，可能已被其他程序占用。请先停止占用程序；不会自动换端口或打开未知服务。") from exc
        url = f"http://127.0.0.1:{port}"
        stopping = threading.Event()
        def open_when_ready():
            import requests
            with requests.Session() as session:
                session.trust_env = False
                for _ in range(30):
                    if stopping.is_set():
                        return
                    try:
                        response = session.get(url + "/_local/ready", timeout=1)
                        if response.ok and response.json().get("application") == "resume-produce":
                            if not stopping.is_set():
                                if not open_in_chrome(url):
                                    print(f"无法自动打开 Google Chrome，请确认已安装，或手动访问 {url}", flush=True)
                            return
                    except (requests.RequestException, ValueError):
                        pass
                    stopping.wait(0.2)
            print(f"浏览器未自动打开，请手动访问 {url}", flush=True)
        if open_browser:
            threading.Thread(target=open_when_ready, daemon=True).start()
        def stop(_signum, _frame):
            raise KeyboardInterrupt
        previous = {}
        for sig in (signal.SIGTERM, signal.SIGHUP):
            previous[sig] = signal.signal(sig, stop)
        print(f"数据目录：{directory}\n本机地址：{url}\n按 Control+C 停止。关闭浏览器不会停止服务；停止后未保存草稿会丢失。", flush=True)
        try:
            server.run()
        except KeyboardInterrupt:
            pass
        finally:
            stopping.set()
            server.close()
            server.task_dispatcher.shutdown()
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            print("服务已停止。", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="简历生成 Agent 本机启动与初始化")
    parser.add_argument("command", nargs="?", choices=("start", "init", "key", "open"), default="start")
    parser.add_argument("--data-dir", help="日常数据目录；其次读取 RESUME_DATA_DIR，否则使用 ~/Library/Application Support/ResumeProduce")
    parser.add_argument("--from-dir", type=Path, help="init：停止旧服务后，从此目录复制现有资料；不删除原件")
    parser.add_argument("--provider", choices=("deepseek", "kimi", "qwen", "openai"), help="key：选择密钥服务商")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--reuse", action="store_true", help="仅复用同一数据目录的已就绪服务")
    parser.add_argument("--no-keychain", action="store_true", help="仅使用环境变量中的 Key（隔离测试用）")
    args = parser.parse_args(argv)
    try:
        if args.command == "key":
            from .keychain import write_key
            from .models import PROVIDERS
            provider = args.provider
            if not provider:
                print("服务商：1 DeepSeek / 2 Kimi 国际 / 3 Qwen 北京 / 4 OpenAI")
                provider = {"1": "deepseek", "2": "kimi", "3": "qwen", "4": "openai"}.get(input("请选择编号：").strip())
                if not provider:
                    raise ValueError("请选择有效编号。")
            key = getpass.getpass(f"{PROVIDERS[provider]['name']} Key（输入不显示；留空取消）：").strip()
            if key:
                write_key(key, provider)
                print("密钥已存入 macOS 钥匙串。请重启已运行的服务。")
            return 0
        directory = data_directory(args.data_dir)
        if args.command == "init":
            initialize(directory, args.from_dir)
            print(f"初始化完成：{directory}\n请编辑 data/profile.yaml、data/skills.yaml 和 config.yaml；密钥使用配置模型密钥.command 设置。")
        elif args.command == "open":
            open_existing(directory)
        else:
            serve(directory, not args.no_browser, not args.no_keychain, args.reuse)
        return 0
    except yaml.YAMLError:
        print("配置或资料 YAML 格式不正确，请检查最近编辑的文件。", file=sys.stderr)
        return 1
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"无法完成：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已取消。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
