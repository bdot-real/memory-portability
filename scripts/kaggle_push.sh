#!/usr/bin/env bash
# Push the large-tier matrix job to Kaggle: code bundle as a private dataset, then the kernel.
#   scripts/kaggle_push.sh e01-e03        # personas for this session
#   uvx kaggle kernels status bdot99/ompm-large
#   uvx kaggle kernels output bdot99/ompm-large -p runs/kaggle/<session>
# Needs KAGGLE_API_KEY in .env. Both the dataset and the kernel are private.
set -euo pipefail
cd "$(dirname "$0")/.."
PERSONAS="${1:?personas, e.g. e01-e03}"
USER_NAME=bdot99
BUILD=runs/kaggle/build
rm -rf "$BUILD" && mkdir -p "$BUILD/bundle" "$BUILD/kernel"
export KAGGLE_API_TOKEN="$(uv run python -c "from ompm.engines import api_key; print(api_key('KAGGLE_API_KEY'))")"

# Code, ontology and the large-tier personas only: no runs, no .env.
COPYFILE_DISABLE=1 tar czf "$BUILD/bundle/ompm.tar.gz" pyproject.toml uv.lock README.md src scripts ontology \
  data/personas/large
cat > "$BUILD/bundle/dataset-metadata.json" <<EOF
{"title": "ompm-bundle", "id": "$USER_NAME/ompm-bundle", "licenses": [{"name": "other"}]}
EOF
if uvx kaggle datasets status "$USER_NAME/ompm-bundle" >/dev/null 2>&1; then
  uvx kaggle datasets version -p "$BUILD/bundle" -m "bundle $(git rev-parse --short HEAD)"
else
  uvx kaggle datasets create -p "$BUILD/bundle"
fi

# The kernel only sees the dataset once Kaggle has finished processing it.
for _ in $(seq 1 40); do
  [ "$(uvx kaggle datasets status "$USER_NAME/ompm-bundle" 2>/dev/null | tail -1)" = ready ] && break
  sleep 15
done

sed "s/^PERSONAS = .*/PERSONAS = \"$PERSONAS\"/" kaggle/run_large.py > "$BUILD/kernel/run_large.py"
cat > "$BUILD/kernel/kernel-metadata.json" <<EOF
{"id": "$USER_NAME/ompm-large", "title": "ompm-large", "code_file": "run_large.py",
 "language": "python", "kernel_type": "script", "is_private": true,
 "enable_gpu": true, "enable_internet": true, "machine_shape": "NvidiaTeslaT4",
 "dataset_sources": ["$USER_NAME/ompm-bundle"]}
EOF
uvx kaggle kernels push -p "$BUILD/kernel"
