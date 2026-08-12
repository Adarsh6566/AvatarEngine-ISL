# tools/ — thin CLI wrappers

One CLI per stage plus a full-run driver and a registrar. Each reads/writes
artifacts via `motionpipe.io` so any stage runs standalone for debugging.

Planned (not yet implemented):
```
extract_pose.py     video      -> output/poses/
reconstruct.py      poses      -> output/motions/
normalize.py        motions    -> output/normalized/
retarget.py         normalized -> output/retargeted/
export_motion.py    retargeted -> output/vrma/ + output/manifest/
run_pipeline.py     dataset    -> full chain (motionpipe.pipeline.Pipeline)
register.py         asset      -> prints merge-ready manifest fragment (never edits runtime)
```
