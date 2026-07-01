#!/usr/bin/env bash
# Orchestrate the NMC campaign only through safe workflow frontiers.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/config/site.env"
CASE="${ROOT}/case"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ERROR: missing ${ENV_FILE}" >&2
  exit 2
fi

# shellcheck disable=SC1090
source "${ENV_FILE}"

WF_CMD="${MONAN_JEDI_WORKFLOW_CMD:-monan-jedi-workflow}"
BMNMC_CMD="${MPASNMC_CMD:-mpasnmc}"
BFLOW_CMD="${MPASBFLOW_CMD:-mpasbflow}"

usage() {
  cat <<EOF
Usage: $0 COMMAND

Commands:
  bootstrap         Generate the JACI-specific experiment YAMLs/templates.
  preflight         Check paths, five inputs and generated files.
  plan              Resolve campaign geometry without running anything.
  status            Show presence/absence of input, restart and mpasout products.
  prepare-init      Fetch remote GFS when configured, execute WPS, and prepare init PBS files only.
  download-inputs   Fetch the five remote GFS inputs and advance only the non-PBS preparation frontier.
  submit-init       Submit the pending init frontier; does not wait.
  prepare-forecast  After init products validate, prepare f024/f048 PBS files and verify namelist contract.
  verify-namelist   Verify rendered f024/f048 namelist and streams against the selected 240-km profile.
  submit-forecast   Submit the pending forecast frontier; does not wait.
  finalize          Validate completed forecasts and export bflow-manifest.tsv.
  run-all-wait      Blocking init -> forecast -> manifest sequence for a small test.
  bflow             Validate manifest and run BFLOW in the bmatrix repository.
EOF
}

run() {
  printf '+ '
  printf '%q ' "$@"
  printf '\n'
  "$@"
}

command="${1:-}"
case "${command}" in
  bootstrap)
    run python3 "${ROOT}/scripts/configure_case.py" --env "${ENV_FILE}"
    ;;
  preflight)
    run python3 "${ROOT}/scripts/preflight.py"
    ;;
  plan)
    run "${WF_CMD}" nmc-campaign-plan "${CASE}"
    ;;
  status)
    run "${WF_CMD}" nmc-campaign-status "${CASE}" --checksum
    ;;
  prepare-init|download-inputs)
    if [[ "${INPUT_MODE,,}" == "download_gfs" ]]; then
      run "${WF_CMD}" nmc-campaign-run "${CASE}" --execute --fetch-inputs
    else
      run "${WF_CMD}" nmc-campaign-run "${CASE}" --execute
    fi
    ;;
  submit-init)
    run "${WF_CMD}" nmc-campaign-run "${CASE}" --execute --submit
    ;;
  prepare-forecast)
    run "${WF_CMD}" nmc-campaign-run "${CASE}" --execute
    run python3 "${ROOT}/scripts/verify_namelist_contract.py"
    ;;
  verify-namelist)
    run python3 "${ROOT}/scripts/verify_namelist_contract.py"
    ;;
  submit-forecast)
    run "${WF_CMD}" nmc-campaign-run "${CASE}" --execute --submit
    ;;
  finalize)
    run "${WF_CMD}" nmc-campaign-run "${CASE}" --execute
    run "${WF_CMD}" nmc-campaign-export-manifest "${CASE}" --checksum
    ;;
  run-all-wait)
    run "${WF_CMD}" nmc-campaign-run "${CASE}" --execute --submit --wait --poll-seconds 30
    run "${WF_CMD}" nmc-campaign-run "${CASE}" --execute --submit --wait --poll-seconds 30
    run python3 "${ROOT}/scripts/verify_namelist_contract.py"
    run "${WF_CMD}" nmc-campaign-run "${CASE}" --execute
    run "${WF_CMD}" nmc-campaign-export-manifest "${CASE}" --checksum
    ;;
  bflow)
    manifest="${CAMPAIGN_ROOT}/bflow-manifest.tsv"
    run "${BMNMC_CMD}" validate-manifest --manifest "${manifest}" --minimum-pairs 4
    run "${BFLOW_CMD}" all \
      --config "${BMATRIX_CONFIG}" \
      --manifest "${manifest}" \
      --workspace "${BFLOW_WORKSPACE}" \
      --minimum-pairs 4 \
      --clean-output
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    echo "ERROR: unknown command ${command!r}" >&2
    usage >&2
    exit 2
    ;;
esac
