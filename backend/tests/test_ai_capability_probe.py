"""Metadata probes must not inherit ambient API/OAuth credentials."""
import runpy
from pathlib import Path


def test_probe_child_environment_excludes_auth_and_config_injection():
    module = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/probe_ai_capabilities.py'))
    supplied = {name: 'synthetic-marker' for name in ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN',
                'CLAUDE_CODE_OAUTH_TOKEN', 'OPENAI_API_KEY', 'CODEX_HOME', 'CLAUDE_CONFIG_DIR',
                'NODE_OPTIONS', 'PYTHONPATH', 'BASH_ENV', 'AWS_ACCESS_KEY_ID']}
    supplied.update({'PATH': '/synthetic/bin', 'HTTPS_PROXY': 'https://proxy.example',
                     'SystemRoot': 'synthetic-system'})
    filtered = module['minimal_environment'](supplied)
    assert filtered == {'PATH': '/synthetic/bin', 'HTTPS_PROXY': 'https://proxy.example',
                        'SystemRoot': 'synthetic-system'}
