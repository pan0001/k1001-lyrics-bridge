# CPU temperature worker and automatic startup

Run `./build.ps1` on Windows with .NET Framework 4.7.2+ to build the worker and
setup tool with the pinned, SHA-256-verified LibreHardwareMonitor 0.9.6 release.
Setup embeds every permitted dependency's SHA-256. No NVIDIA SDK is included.

An explicit configuration click plus Windows UAC installs verified files into
`%ProgramFiles%/SkyLyrics Sensors/<user SID>/<build hash>/`. Only Administrators
and SYSTEM may write here; the target user has read/execute access. Reparse
directories/files and unexpected content are rejected. The per-user task
`SkyLyricsSensors-<SID>` runs this fixed protected executable with `--persistent
<SID>` five seconds after logon, HighestAvailable, InteractiveToken (no password
saved). It works on battery and has no execution time limit. The user may read/run
but not edit its elevated action. Setup suppresses Task Scheduler's automatic
principal ACE to preserve this read/run-only task DACL.

The configured user must be a Windows administrator. Entering another admin's
credentials does not elevate a standard user's logon token. PawnIO must already
be installed; driver installation is not automated. The main UI and lyrics stay
unelevated. A restart reconnects to the protected worker without UAC. If needed,
the app may run this pre-authorized task at most once/minute. This never recreates
a missing task or changes its permissions. Missing setup requires a manual click.

The worker pipe allows only this SID and denies network logons. One byte (S) per
connection requests a temperature/status; no file paths, shell commands or
hardware-setting operations are accepted. The client verifies the server PID's
executable against the protected installation marker. Connections time out after
three seconds. Reads are cached at most one second, only CPU monitoring is
enabled, and 20 seconds without requests releases hardware. Native reads hung
over 20 seconds exit to let Task Scheduler recover. Disconnecting the GUI does
not stop the login task; it stays idle without sampling.

The disable button stops/deletes the task and marker (UAC required). Verified
binaries are retained; no recursive deletion is performed. Main app startup and
sensor startup have separate controls. Legacy temporary-parent mode is retained
for diagnostics. Sensor selection prefers CPU package/Tctl over cores/CCDs;
invalid zero/NaN/infinite/out-of-range values are unavailable.

Original code: GPL-3.0-only. Unmodified separate LibreHardwareMonitor DLL:
MPL-2.0. Embedded PawnIO modules: LGPL-2.1. Complete notices, dependency metadata
and source archives are under `licenses/cpu-sensors/`. Driver official project:
https://github.com/namazso/PawnIO . No sensor values are included in artifacts.
