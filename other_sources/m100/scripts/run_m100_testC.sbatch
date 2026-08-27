#!/bin/bash
#SBATCH -J m100_tC
#SBATCH -p mit_data_transfer
#SBATCH -N 1
#SBATCH -c 1
#SBATCH --mem=1G
#SBATCH -t 00:30:00
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/testC_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/testC_%j.err
set -uo pipefail
OUT=/orcd/scratch/orcd/008/nacevedo/m100/tests/testC_net.txt
mkdir -p /orcd/scratch/orcd/008/nacevedo/m100/tests
{
  echo "host=$(hostname) job=${SLURM_JOB_ID} date=$(date -Is)"
  echo "=== HEAD zenodo record ==="
  curl -sI --max-time 30 "https://zenodo.org/api/records/7589320" | head -20
  echo "=== HEAD file content ==="
  curl -sI --max-time 30 "https://zenodo.org/api/records/7589320/files/21-07.tar/content" | head -30
  echo "=== range GET 0-1023 ==="
  curl -sI --max-time 30 -H "Range: bytes=0-1023" "https://zenodo.org/api/records/7589320/files/21-07.tar/content" | head -20
  echo "=== TEST D wget -c ==="
  PART=/orcd/scratch/orcd/008/nacevedo/m100/tests/resume_partial.bin
  URL="https://zenodo.org/api/records/7589320/files/21-07.tar/content"
  rm -f "${PART}"
  curl -L --max-time 90 -r 0-1048575 -o "${PART}" "${URL}"
  echo "partial_bytes=$(wc -c < "${PART}")"
  wget -c --timeout=20 --tries=1 -O "${PART}" "${URL}" || true
  echo "after_wget_c_bytes=$(wc -c < "${PART}")"
} | tee "${OUT}"
grep -qi "HTTP/" "${OUT}"
echo TEST_C_OK
if grep -qi "Accept-Ranges" "${OUT}"; then echo TEST_D_RANGES_OK; fi
if [ "$(wc -c < /orcd/scratch/orcd/008/nacevedo/m100/tests/resume_partial.bin)" -ge 1048576 ]; then echo TEST_D_OK; fi
