#!/bin/sh
# Copies the shared citation styles into Cite.html, which Apps Script needs as an HTML file.
# Run after changing extension/library/cite.js.
cd "$(dirname "$0")"
{ echo "<script>"; cat ../extension/library/cite.js; echo "</script>"; } > Cite.html
