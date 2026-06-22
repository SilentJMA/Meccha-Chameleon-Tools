#!/usr/bin/env python3
"""Print dynamically resolved engine offsets."""
from meccha_chameleon_tools import MecchaESP

esp = MecchaESP()
for key, val in sorted(esp.offsets.items()):
    print(f"{key:45} = 0x{val:X}")
