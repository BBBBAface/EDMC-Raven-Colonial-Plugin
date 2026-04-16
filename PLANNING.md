# Raven Colonial HUD Sync - Implementation Guide

## Objective
Provide a lightweight, non-blocking Tkinter HUD overlay for Elite Dangerous on Linux/Proton environments, syncing data with EDSM and Raven Colonial APIs.

## Agent Workflow & Failsafes
1. **Hardware Initialization (`setup.py`)**: Executes vendor profiling (NVIDIA, AMD, Intel) to determine if the host compositor supports native X11/Wayland window transparency. Falls back to an opaque black background if compositing fails.
2. **Robust Validation (`conftest.py`)**: Simulates network timeouts, malformed Journal entries, and legacy hardware to ensure the plugin fails gracefully without taking down Canonn or EDMC.
3. **Execution & Streaming (`load.py`)**: 
    - Implements `requests.Session()` for optimized HTTP keep-alive.
    - Isolates all network I/O to background daemon threads.
    - Hooks `plugin_stop()` to forcibly destroy the Tkinter loop, preventing memory leaks and plugin conflicts.