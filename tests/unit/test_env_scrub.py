import json
from pathlib import Path

from runner.workdir import ALLOWED_ENV_KEYS, build_agent_env, harness_settings

HOST = {
    "PATH": "/usr/bin:/bin", "HOME": "/Users/me", "USER": "me", "LOGNAME": "me", "LANG": "en_US.UTF-8",
    "TERM": "xterm", "SHELL": "/bin/zsh", "GITHUB_TOKEN": "ghp_x", "AWS_ACCESS_KEY_ID": "AKIA",
    "AWS_SECRET_ACCESS_KEY": "s", "SSH_AUTH_SOCK": "/tmp/agent.sock", "ANTHROPIC_API_KEY": "sk-ant-x",
    "ANTHROPIC_MODEL": "claude-haiku", "CLAUDE_CONFIG_DIR": "/elsewhere", "OPENAI_API_KEY": "k",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://evil:4317", "VIRTUAL_ENV": "/some/venv",
    "PYTHONPATH": "/repo",
}


def env(**kw):
    base = dict(host_env=HOST, tmpdir=Path("/work/r1/tmp"), path_dirs=["/work/r1/venv/bin", "/usr/local/bin"],
                otel_endpoint="http://127.0.0.1:4318", protocol="http/json", export_interval_ms=1000,
                resource_attrs={"lrae.run_id": "r1", "lrae.config": "A", "lrae.repeat": "0"})
    base.update(kw)
    return build_agent_env(**base)


def test_only_allowlisted_keys():
    e = env()
    extra = {k for k in e if k not in ALLOWED_ENV_KEYS and not k.startswith("OTEL_")}
    assert not extra, extra


def test_host_secrets_dropped():
    e = env()
    for k in ("GITHUB_TOKEN", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "SSH_AUTH_SOCK",
              "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "CLAUDE_CONFIG_DIR", "OPENAI_API_KEY",
              "SHELL", "VIRTUAL_ENV", "PYTHONPATH"):
        assert k not in e, k


def test_home_is_real_and_tmpdir_in_work():
    e = env()
    assert e["HOME"] == "/Users/me" and e["USER"] == "me" and e["LOGNAME"] == "me"
    assert e["TMPDIR"] == "/work/r1/tmp"


def test_path_is_constructed_not_inherited():
    e = env()
    assert e["PATH"].split(":")[:2] == ["/work/r1/venv/bin", "/usr/local/bin"]
    assert "/usr/bin" in e["PATH"].split(":")


def test_otel_vars_are_harness_controlled_not_host():
    e = env()
    assert e["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://127.0.0.1:4318"
    assert e["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    assert e["OTEL_METRICS_EXPORTER"] == "otlp" and e["OTEL_LOGS_EXPORTER"] == "otlp"
    assert e["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/json"
    assert e["OTEL_METRIC_EXPORT_INTERVAL"] == "1000" and e["OTEL_LOGS_EXPORT_INTERVAL"] == "1000"
    attrs = dict(kv.split("=") for kv in e["OTEL_RESOURCE_ATTRIBUTES"].split(","))
    assert attrs == {"lrae.run_id": "r1", "lrae.config": "A", "lrae.repeat": "0"}


def test_updater_and_traffic_flags():
    e = env()
    assert e["DISABLE_AUTOUPDATER"] == "1"
    assert e["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"


def test_missing_host_vars_are_omitted_not_empty():
    e = env(host_env={"PATH": "/bin"})
    assert "HOME" not in e and "USER" not in e


def test_harness_settings_carries_otel_env_and_is_json():
    s = harness_settings(otel_endpoint="http://127.0.0.1:4318", protocol="http/json",
                         export_interval_ms=500, resource_attrs={"lrae.run_id": "r1"})
    parsed = json.loads(json.dumps(s))
    assert parsed["env"]["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    assert parsed["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://127.0.0.1:4318"
    assert parsed["env"]["OTEL_METRIC_EXPORT_INTERVAL"] == "500"


def test_harness_settings_switches_builtin_plugins_off():
    """Verified on CLI 2.1.301 (B1 verification turn): with these entries init.plugins is []."""
    s = harness_settings(otel_endpoint="http://127.0.0.1:4318", protocol="http/json",
                         export_interval_ms=1000, resource_attrs={})
    assert s["enabledPlugins"] == {"cc-plugin-agents-md@builtin": False,
                                   "cc-plugin-plugin-authoring@builtin": False}
