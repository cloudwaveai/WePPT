# Bundled upstream skill distributions

Complete original package snapshots; licenses and attribution files are inside each archive. See manifest.json for source repository, commit, source directory, file count, archive hash and license. These ZIPs are shipped with the app, not fetched at runtime.

Install: `npm run setup:skills`. List: `npm run skills:status`.

Local converter: `npm run skills:convert-svg -- <workspace containing svg_output> <output.pptx>`; this invokes the original final SVG quality gate, then the native converter. It does not import the result into the web editor or bypass review.

Installed files live under ignored data/upstream-skills/<package>/<commit>. Do not edit upstream copies; write adapters outside. Complete packaging does not imply every upstream dependency or workflow is active. See ../../docs/upstream-skills.md.
