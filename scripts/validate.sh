#!/usr/bin/env bash
set -euo pipefail

plugin_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

python3 -m json.tool "${plugin_dir}/manifest.json" >/dev/null
python3 -m json.tool "${plugin_dir}/models.lock.json" >/dev/null
grep -q -- '--hash=sha256:' "${plugin_dir}/requirements.lock"
grep -q -- '--hash=sha256:' "${plugin_dir}/build-requirements.lock"
python3 -m py_compile "${plugin_dir}/stem_tool.py" "${plugin_dir}/engine_runner.py"
PYTHONPATH="${plugin_dir}" python3 -m unittest discover -s "${plugin_dir}/tests" -v

if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin validate "${plugin_dir}"
fi

if command -v qmllint >/dev/null 2>&1 && [[ -d /usr/share/omarchy/shell ]]; then
  qmllint -I /usr/share/omarchy/shell "${plugin_dir}/BarWidget.qml" "${plugin_dir}/Panel.qml"
fi
