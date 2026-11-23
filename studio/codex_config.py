"""Read only provider connection settings, not tools, permissions or project instructions."""
import json
import os
from pathlib import Path
import tomllib

path = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'config.toml'
try:
    config = tomllib.loads(path.read_text(encoding='utf-8'))
except (OSError, ValueError):
    config = {}
selected = config.get('model_provider', 'openai')
provider = config.get('model_providers', {}).get(selected, {})
args = ['-c', 'model_provider=' + json.dumps(selected)]
environment = {}
for key in ('name', 'base_url', 'env_key', 'wire_api', 'requires_openai_auth'):
    value = provider.get(key)
    if isinstance(value, (str, bool)):
        args += ['-c', f'model_providers.{selected}.{key}=' + json.dumps(value)]
if provider.get('experimental_bearer_token') and not provider.get('env_key'):
    environment['WEPPT_AI_PROVIDER_TOKEN'] = provider['experimental_bearer_token']
    args += ['-c', f'model_providers.{selected}.env_key="WEPPT_AI_PROVIDER_TOKEN"']
print(json.dumps({'args': args, 'env': environment}))
