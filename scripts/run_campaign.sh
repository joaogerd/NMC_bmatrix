#!/usr/bin/env bash
set -euo pipefail

# The package location is immutable. Site configuration may define only runtime
# and infrastructure paths, never package/script roots.
PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${PACKAGE_ROOT}/config/site.env"
CASE_DIR="${PACKAGE_ROOT}/case"
STATIC_CASE_DIR="${CASE_DIR}/static"
STATIC_CYCLE="2010-10-23T00:00:00Z"

init_config() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    cp "${PACKAGE_ROOT}/config/site.env.example" "${ENV_FILE}"
    echo "Created ${ENV_FILE}. Edit it, then rerun the command." >&2
    exit 2
  fi
}

reject_legacy_env() {
  if grep -Eq '^[[:space:]]*(ROOT|WORK_ROOT|RAW_GFS_ROOT|WPS_OUTPUT_ROOT|MPAS_INIT_ROOT|MPAS_RUN_ROOT|BFLOW_WORKSPACE)=' "${ENV_FILE}"; then
    cat >&2 <<'EOFMSG'
ERROR: config/site.env is from an older split-root layout.
This package accepts CAMPAIGN_ROOT as the only mutable runtime root.
Replace config/site.env from config/site.env.example, then edit site paths.
EOFMSG
    exit 2
  fi
}

run() { printf '+ '; printf '%q ' "$@"; printf '\n'; "$@"; }

require_static() {
  run "${WF}" mpas-init-validate "${STATIC_CASE_DIR}" --cycle "${STATIC_CYCLE}"
}

init_config
reject_legacy_env
# shellcheck disable=SC1090
source "${ENV_FILE}"
WF="${MONAN_JEDI_WORKFLOW_CMD:-monan-jedi-workflow}"
NMC="${MPASNMC_CMD:-mpasnmc}"
BFLOW="${MPASBFLOW_CMD:-mpasbflow}"

case "${1:-}" in
  bootstrap)
    run python3 "${PACKAGE_ROOT}/scripts/configure_case.py" --env "${ENV_FILE}"
    ;;
  preflight)
    run python3 "${PACKAGE_ROOT}/scripts/preflight.py"
    ;;
  prepare-static)
    run "${WF}" mpas-init-prepare "${STATIC_CASE_DIR}" --cycle "${STATIC_CYCLE}"
    ;;
  submit-static)
    run "${WF}" mpas-init-submit "${STATIC_CASE_DIR}" --cycle "${STATIC_CYCLE}"
    ;;
  validate-static)
    require_static
    ;;
  plan)
    run "${WF}" nmc-campaign-plan "${CASE_DIR}"
    ;;
  status)
    run "${WF}" nmc-campaign-status "${CASE_DIR}" --checksum
    ;;
  prepare-init)
    require_static
    if [[ "${INPUT_MODE,,}" == "download_gfs" ]]; then
      run "${WF}" nmc-campaign-run "${CASE_DIR}" --execute --fetch-inputs
    else
      run "${WF}" nmc-campaign-run "${CASE_DIR}" --execute
    fi
    ;;
  submit-init)
    require_static
    run "${WF}" nmc-campaign-run "${CASE_DIR}" --execute --submit
    ;;
  prepare-forecast)
    require_static
    run "${WF}" nmc-campaign-run "${CASE_DIR}" --execute
    run python3 "${PACKAGE_ROOT}/scripts/verify_namelist_contract.py"
    ;;
  submit-forecast)
    require_static
    run "${WF}" nmc-campaign-run "${CASE_DIR}" --execute --submit
    ;;
  finalize)
    require_static
    run "${WF}" nmc-campaign-run "${CASE_DIR}" --execute
    run "${WF}" nmc-campaign-export-manifest "${CASE_DIR}" --checksum
    ;;
  bflow)
    manifest="${CAMPAIGN_ROOT}/campaign/bflow-manifest.tsv"
    run "${NMC}" validate-manifest --manifest "${manifest}" --minimum-pairs 4
    run "${BFLOW}" all --config "${BMATRIX_CONFIG}" --manifest "${manifest}" \
      --workspace "${CAMPAIGN_ROOT}/bflow" --minimum-pairs 4 --clean-output
    ;;
  clean-generated)
    rm -rf "${CASE_DIR}/templates" "${CASE_DIR}/inventory" "${STATIC_CASE_DIR}"
    rm -f "${CASE_DIR}/workflow.yaml" "${CASE_DIR}/inputs.yaml" "${CASE_DIR}/wps.yaml" \
      "${CASE_DIR}/mpas_init.yaml" "${CASE_DIR}/mpas.yaml"
    rm -f "${PACKAGE_ROOT}/bin/run_with_jaci_env.sh" "${PACKAGE_ROOT}/bin/mpiexec_with_jaci_env.sh"
    echo "Removed generated case files only. Runtime under CAMPAIGN_ROOT was not touched."
    ;;
  *)
    cat <<'EOFUSAGE'
Usage:
  bootstrap          generate both static and dynamic YAML/template contracts
  preflight          validate software, WPS_GEOG, templates and one-root contract
  prepare-static     prepare the one-time x1.<mesh>.static.nc PBS run
  submit-static      submit the static interpolation job
  validate-static    validate x1.<mesh>.static.nc after the job has completed
  plan               write the NMC f024/f048 plan
  prepare-init       require a validated static product, then fetch GFS/run WPS/prepare five init jobs
  submit-init        submit five date-dependent init jobs
  prepare-forecast   after valid inits, prepare eight f024/f048 forecast jobs
  submit-forecast    submit eight forecast jobs
  finalize           validate forecasts and export bflow-manifest.tsv
  bflow              execute BFLOW from the exported manifest
  status             inspect campaign products
  clean-generated    remove only generated YAML/template files
EOFUSAGE
    exit 2
    ;;
esac
