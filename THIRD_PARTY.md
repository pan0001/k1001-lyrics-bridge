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
- Pillow: HPND, https://github.com/python-pillow/Pillow
- PyInstaller bootloader: GPL with bootloader exception, https://pyinstaller.org/en/stable/license.html

Dependencies retain their upstream licenses. The Python package requirements are
listed in requirements.txt. No song audio, lyric cache, user logs, or account data
is included in the release.
