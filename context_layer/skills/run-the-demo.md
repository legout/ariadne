---
type: skill
status: draft
title: Run the demo
description: End-to-end demo via examples/retail-demo/demo.sh.
tags:
- skill
- demo
sources:
- id: demo-script
  resource: examples/retail-demo/demo.sh
  title: demo.sh
generated:
  by: ariadne-author
  at: '2026-09-18T12:06:35+00:00'
verified: []
stale_after: '2026-12-17'
---

# Run the demo

cd examples/retail-demo && python seed_db.py data/demo.db && ./demo.sh
