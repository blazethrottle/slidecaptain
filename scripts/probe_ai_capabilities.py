"""Read official CLI metadata in disposable profiles and sanitized child environments.

No prompt, turn, login, account/read, credential copying or paid generation.
Only allowlisted model metadata is saved, never raw initialization responses.
Catalog presence does not prove account access or model performance.
"""
import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

EFFORTS = {'low', 'medium', 'high', 'xhigh', 'max', 'ultra'}


def minimal_environment(source):
    allowed = {'PATH', 'HOME', 'USERPROFILE', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT',
               'TEMP', 'TMP', 'LANG', 'LC_ALL', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
               'NO_PROXY', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE',
               'NODE_EXTRA_CA_CERTS', 'SLIDECAPTAIN_CLAUDE_CLI', 'SLIDECAPTAIN_CODEX_CLI'}
    return {key: value for key, value in source.items() if key.upper() in allowed}


def text(value):
    return value if isinstance(value, str) and len(value) <= 200 else None


async def claude(directory):
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
    from slidecaptain.pipeline.auth_status import resolve_cli_path
    cli = resolve_cli_path()
    if cli is None:
        raise RuntimeError('CLIUnavailable')
    options = ClaudeAgentOptions(cli_path=str(cli), cwd=str(directory), tools=[], setting_sources=[],
                                env={'CLAUDE_CONFIG_DIR': str(directory), 'DISABLE_TELEMETRY': '1'}, max_turns=1)
    async with ClaudeSDKClient(options=options) as client:
        info = await asyncio.wait_for(client.get_server_info(), timeout=30)
        models = []
        for item in info.get('models', [])[:100]:
            if not isinstance(item, dict) or not text(item.get('value')):
                continue
            models.append({'id': item['value'], 'resolved_model': text(item.get('resolvedModel')),
                           'label': text(item.get('displayName')),
                           'efforts': [effort for effort in item.get('supportedEffortLevels', []) if effort in EFFORTS]})
        return {'sdk_version': version('claude-agent-sdk'), 'models': models}


def codex(directory):
    from slidecaptain.pipeline.codex import CodexRPC
    client = CodexRPC(directory)
    try:
        models, seen, cursor = [], set(), None
        for _ in range(10):
            data = client.request('model/list', {'limit': 100, 'includeHidden': False, 'cursor': cursor})
            for item in data.get('data', []):
                if not isinstance(item, dict) or not text(item.get('model')) or item['model'] in seen:
                    continue
                seen.add(item['model'])
                models.append({'id': item['model'], 'label': text(item.get('displayName')),
                               'efforts': [effort['reasoningEffort'] for effort in item.get('supportedReasoningEfforts', [])
                                           if isinstance(effort, dict) and effort.get('reasoningEffort') in EFFORTS],
                               'default_effort': text(item.get('defaultReasoningEffort'))})
            cursor = data.get('nextCursor')
            if not cursor:
                break
        return {'models': models}
    finally:
        client.close()


async def worker(provider):
    from slidecaptain.desktop_processes import ProcessFence
    fence = ProcessFence()  # Windows handle stays alive until worker exit.
    with tempfile.TemporaryDirectory(prefix=f'slidecaptain-{provider}-metadata-') as temporary:
        try:
            result = await claude(Path(temporary)) if provider == 'claude' else await asyncio.to_thread(codex, Path(temporary))
            return {'status': 'catalog_observed', **result}
        except Exception as exc:
            return {'status': 'unavailable', 'error_type': type(exc).__name__}


def probe(output):
    report = {'generation_calls': 0, 'authenticated_profiles_tested': False,
              'inherited_auth_environment': 'excluded', 'os_credential_store_isolation': 'unverified', 'providers': {}}
    root = Path(__file__).resolve().parents[1]
    environment = {**minimal_environment(os.environ), 'PYTHONPATH': str(root / 'backend'),
                   'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    for provider in ['claude', 'chatgpt']:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', provider],
                                   env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=os.name != 'nt')
        try:
            stdout, _ = process.communicate(timeout=120)
            if process.returncode or len(stdout) > 1024 * 1024:
                raise ValueError('InvalidWorkerOutput')
            report['providers'][provider] = json.loads(stdout)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            report['providers'][provider] = {'status': 'unavailable', 'error_type': 'TimeoutExpired'}
        except (ValueError, OSError):
            report['providers'][provider] = {'status': 'unavailable', 'error_type': 'InvalidWorkerOutput'}
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({provider: {'status': result['status'], 'models': len(result.get('models', []))}
                      for provider, result in report['providers'].items()}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--worker', choices=['claude', 'chatgpt'], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(asyncio.run(worker(args.worker))))
        return
    if args.out is None:
        parser.error('--out is required')
    root = Path(__file__).resolve().parents[1]
    output = args.out.resolve()
    if output.exists() or output == root or root in output.parents:
        raise SystemExit('Use a new output file outside the checkout')
    output.parent.mkdir(parents=True, exist_ok=True)
    probe(output)


if __name__ == '__main__':
    main()
