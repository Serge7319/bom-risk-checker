#!/usr/bin/env bash
set -euo pipefail
if [ -d "pages" ]; then
  mkdir -p old_streamlit_pages
  mv pages/* old_streamlit_pages/ 2>/dev/null || true
  rmdir pages 2>/dev/null || true
  echo "Moved Streamlit native pages into old_streamlit_pages/."
else
  echo "No pages/ folder found."
fi
