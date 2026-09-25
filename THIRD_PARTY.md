# Third-party code and licenses

This combined application is distributed under GPL-3.0-only; see LICENSE.txt.
Complete corresponding application source and build instructions are included.

## Local QRC decoder

Files `qrc_des.py` and `qrc_mask.py` derive from:
https://github.com/chenmozhijin/LDDC/tree/main/LDDC/core/decryptor

Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
SPDX-License-Identifier: GPL-3.0-only

Original attribution headers are retained. Modification: qrc_des.py uses
functools.lru_cache in place of LDDC's application-level caching dependency.

## Runtime dependencies

- Python: PSF license, https://www.python.org/psf/license/
- PyWinRT: MIT, https://github.com/pywinrt/pywinrt
- pystray: LGPL-3.0, https://github.com/moses-palmer/pystray
- psutil: BSD-3-Clause, https://github.com/giampaolo/psutil
- Pillow: HPND, https://github.com/python-pillow/Pillow
- PyInstaller bootloader: GPL with bootloader exception, https://pyinstaller.org/en/stable/license.html

Dependencies retain their upstream licenses. The Python package requirements are
listed in requirements.txt. No song audio, lyric cache, user logs, or account data
is included in the release.


## Built-in CPU sensor worker (v1.1.2)

- LibreHardwareMonitor 0.9.6, MPL-2.0. Unmodified separate DLL.
  https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/tree/v0.9.6
  Source commit: 3d331e3370efb858411f19511373eff65a218701.
- Embedded PawnIO.Modules 0.1.6, LGPL-2.1, unchanged.
  https://github.com/namazso/PawnIO.Modules/tree/0.1.6
- Their full source archives and licenses are in `licenses/cpu-sensors/`.
- Additional managed runtime dependencies retain their upstream licenses in
  `licenses/cpu-sensors/dependencies/`.

The sensor worker is original GPL-3.0-only code. No NVIDIA SDK is redistributed.
The system PawnIO driver is not bundled or installed by the app.
