"""Use Hermes' supported config writer. Never print credentials or invoke cloud models."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

import yaml


def main():
    project = Path(__file__).resolve().parents[1]
    settings = json.loads((project / 'config/local.json').read_text(encoding='utf-8-sig'))
    home = Path(settings['hermes_home'])
    launcher = home / 'hermes-agent/.hermes/bin/hermes.exe'
    path = home / 'config.yaml'
    original = path.read_text(encoding='utf-8-sig')
    config = yaml.safe_load(original) or {}
    backup = project / 'state' / f'hermes-local-config-{time.time_ns()}.yaml.backup'
    backup.write_text(original, encoding='utf-8')
    # The loopback key stays in Hermes' secret store. It never appears in argv or logs.
    key = (project / 'state/local-model.key').read_text(encoding='utf-8').strip()
    envpath = home / '.env'
    lines = envpath.read_text(encoding='utf-8-sig').splitlines() if envpath.exists() else []
    lines = [line for line in lines if line.partition('=')[0].strip().removeprefix('export ') != 'ERMCLIP_LOCAL_API_KEY']
    lines.append('ERMCLIP_LOCAL_API_KEY=' + key)
    temporary = envpath.with_suffix('.env.ermclip.tmp')
    temporary.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    temporary.replace(envpath)
    route = {'provider': 'custom', 'model': settings['director_model'],
             'base_url': settings['local_llm_url'], 'api_key': '${ERMCLIP_LOCAL_API_KEY}',
             'extra_body': {'chat_template_kwargs': {'enable_thinking': False}}}
    providers = dict(config.get('providers') or {})
    providers['ermclip_local'] = {k: v for k, v in route.items() if k not in ('provider', 'model')}
    model = dict(config.get('model') or {})
    model.update(default=settings['director_model'], provider='ermclip_local',
                 base_url=settings['local_llm_url'], api_key='${ERMCLIP_LOCAL_API_KEY}', context_length=settings.get('local_context_tokens', 32768))
    # Pin every shipped auxiliary lane. A selected main provider blocks discovery of other accounts.
    tasks = ('vision compression skills_hub approval review mcp title_generation memory_query_rewrite '
             'tts_audio_tags voice_chat triage_specifier kanban_decomposer profile_describer goal_judge '
             'curator monitor background_review moa_reference web_extract session_search').split()
    auxiliary = dict(config.get('auxiliary') or {})
    auxiliary['free_only'] = True
    for name in tasks:
        block = dict(auxiliary.get(name) or {})
        block.update(route, fallback_chain=[], timeout=300)
        if name in ('vision', 'background_review', 'title_generation'):
            block['enabled'] = False
        auxiliary[name] = block
    delegation = dict(config.get('delegation') or {})
    delegation.update(provider='ermclip_local', model=settings['director_model'], fallback_providers=[])
    terminal = dict(config.get('terminal') or {})
    terminal.update(backend='local', cwd=str(project))
    stt = dict(config.get('stt') or {})
    stt['provider'] = 'local'
    stt['use_gateway'] = False
    tts = dict(config.get('tts') or {})
    tts['provider'] = 'piper'
    tts['use_gateway'] = False
    allowed = list(config.get('command_allowlist') or [])
    for health_command in (f'powershell.exe -NoProfile -File "{project.as_posix()}/scripts/ermclip.ps1" health',
                           f'powershell.exe -NoProfile -File {project.as_posix()}/scripts/ermclip.ps1 health'):
        if health_command not in allowed:
            allowed.append(health_command)
    changes = {'providers': providers, **{'model.' + k: v for k, v in model.items()}, 'fallback_providers': [],
               'auxiliary': auxiliary, 'delegation': delegation, 'terminal': terminal,
               'command_allowlist': allowed, 'stt': stt, 'tts': tts}
    environment = dict(os.environ, HERMES_HOME=str(home), PYTHONIOENCODING='utf-8')
    for field, value in changes.items():
        # Hermes requires --force for an explicit whole-section replacement.
        result = subprocess.run([str(launcher), 'config', 'set', '--force', field, json.dumps(value) if not isinstance(value, str) else value],
                                env=environment, capture_output=True, text=True, encoding='utf-8', timeout=90)
        if result.returncode:
            raise RuntimeError(f'Hermes refused setting {field}; original config backup: {backup}')
        print(f'Configured {field}', flush=True)
    print(json.dumps({'provider': 'ermclip_local', 'model': settings['director_model'],
                      'endpoint': settings['local_llm_url'], 'cloud_fallbacks': 0, 'backup': str(backup)}))


if __name__ == '__main__':
    main()
