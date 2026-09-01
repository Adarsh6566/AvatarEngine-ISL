"""Canonical motion — one representative clip per sign, learned from all takes.

The runtime plays one recorded take per sign. This package replaces that
arbitrary choice with the DTW barycenter of every usable take, so the clip that
ships is the average performance rather than whichever one was picked.
"""
