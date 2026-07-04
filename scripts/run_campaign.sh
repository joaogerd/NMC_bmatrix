#!/usr/bin/env bash
set -euo pipefail

# This repository configures an MPAS-only producer. It does not call
# monan-jedi-workflow or execute any B-matrix algorithm directly.
PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${PACKAGE_ROOT}/config/site.env"
CASE_DIR="${PACKAGE_ROOT}/case"
MPASWF_CONFIG="${CASE_DIR}/mpaswf.yaml"

run() { printf '+ '; printf '%q ' "$@"; printf '\n'; "$@"; }

init_config() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    cp "${PACKAGE_ROOT}/config/site.env.example" "${ENV_FILE}"
    echo "Created ${ENV_FILE}. Edit it, then rerun the command." >&2
    exit 2
  fi
}

require_bootstrap() {
  if [[ ! -f "${MPASWF_CONFIG}" ]]; then
    echo "Missing ${MPASWF_CONFIG}. Run: ./scripts/run_campaign.sh bootstrap" >&2
    exit 2
  fi
}

init_config
# shellcheck disable=SC1090
source "${ENV_FILE}"
MPASWF="${MPASWF_CMD:-mpaswf}"
NMC="${MPASNMC_CMD:-mpasnmc}"
BFLOW="${MPASBFLOW_CMD:-mpasbflow}"

command="${1:-}"
shift || true

case "${command}" in
  bootstrap)
    run python3 "${PACKAGE_ROOT}/scripts/configure_mpaswf.py" --env "${ENV_FILE}"
    ;;
  preflight)
    require_bootstrap
    run python3 "${PACKAGE_ROOT}/scripts/preflight_mpaswf.py" \
      --config "${MPASWF_CONFIG}" --mpaswf "${MPASWF}"
    ;;
  prepare)
    require_bootstrap
    run "${MPASWF}" run --phase prepare --config "${MPASWF_CONFIG}" "$@"
    ;;
  init)
    require_bootstrap
    run "${MPASWF}" run --phase init --config "${MPASWF_CONFIG}" "$@"
    ;;
  forecast)
    require_bootstrap
    run "${MPASWF}" run --phase forecast --config "${MPASWF_CONFIG}" "$@"
    ;;
  manifest)
    require_bootstrap
    run "${MPASWF}" run --phase manifest --config "${MPASWF_CONFIG}"
    run python3 "${PACKAGE_ROOT}/scripts/export_bflow_manifest.py" \
      --input "${CAMPAIGN_ROOT}/products/mpas-forecast-manifest.tsv" \
      --output "${CAMPAIGN_ROOT}/products/bflow-manifest.tsv"
    ;;
  bflow)
    manifest="${CAMPAIGN_ROOT}/products/bflow-manifest.tsv"
    run "${NMC}" validate-manifest --manifest "${manifest}" --minimum-pairs 4
    run "${BFLOW}" all --config "${BMATRIX_CONFIG}" --manifest "${manifest}" \
      --workspace "${CAMPAIGN_ROOT}/bflow" --minimum-pairs 4 --clean-output
    ;;
  status)
    require_bootstrap
    find "${CAMPAIGN_ROOT}/.mpaswf" -maxdepth 1 -type f -name '*.json' -print -exec cat {} \; 2>/dev/null || true
    if [[ -f "${CAMPAIGN_ROOT}/products/bflow-manifest.tsv" ]]; then
      echo "--- ${CAMPAIGN_ROOT}/products/bflow-manifest.tsv"
      cat "${CAMPAIGN_ROOT}/products/bflow-manifest.tsv"
    fi
    ;;
  clean-generated)
    rm -rf "${CASE_DIR}/templates"
    rm -f "${CASE_DIR}/mpaswf.yaml"
    echo "Removed generated mpaswf configuration and templates only. Runtime products under CAMPAIGN_ROOT were not touched."
    ;;
  *)
    cat <<'EOFUSAGE'
Usage:
  bootstrap              render the small mpaswf configuration and CD-CT templates
  preflight              validate mpaswf, static inputs, executables, and templates
  prepare [--force]      download missing GFS files and produce WPS FILE:* products
  init [--submit --wait] prepare or submit all MPAS initialization jobs
  forecast [--submit --wait]
                         prepare or submit all f024/f048 MPAS forecast jobs
  manifest               validate MPAS products and write MPAS plus BFLOW manifests
  bflow                  run BFLOW using products/bflow-manifest.tsv
  status                 print persisted mpaswf phase records and the BFLOW manifest
  clean-generated        remove only generated mpaswf configuration/templates
EOFUSAGE
    exit 2
    ;;
esac
