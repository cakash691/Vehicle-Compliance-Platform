"""
plates.py -- one plate format for every source.

Each source writes plates its own way: the registry in lower case, insurers with hyphens
or spaces (and with or without the RTO's leading zero), cameras in capitals with the odd
misread. canonical_plate() turns any of them into one form, or says why it can't.

    standard  state code, RTO number padded to 2 digits, 1-2 series letters, 4 digits
    Delhi     RTO number without a leading zero, then the class letter and series
    BH        YY BH #### XX (Bharat series)

>>> canonical_plate("MH-4-AB-1234")          # an insurer that drops the RTO's leading zero
('MH04AB1234', 'STANDARD')
>>> canonical_plate("mh04ab1234")            # the registry
('MH04AB1234', 'STANDARD')
>>> canonical_plate("DL-06-SCP-2349")        # an insurer that pads Delhi's RTO number
('DL6SCP2349', 'DELHI')
>>> canonical_plate("DL 6 SCP 2349")         # a police FIR
('DL6SCP2349', 'DELHI')
>>> canonical_plate("22 BH 1234 AA")
('22BH1234AA', 'BH')
>>> canonical_plate("")                      # a camera that could not read the plate
(None, 'EMPTY')
>>> canonical_plate("MH39VV52B1")            # a camera misread (8 read as B)
(None, 'INVALID_FORMAT')

Run `python3 -m pipeline.plates` to check these examples.
"""

import re

BH = re.compile(r"(\d{2})BH(\d{4})([A-Z]{2})")
DELHI = re.compile(r"DL0?(\d{1,2})([A-Z]{2,3})(\d{4})")        # checked before STANDARD:
STANDARD = re.compile(r"([A-Z]{2})(\d{1,2})([A-Z]{1,2})(\d{4})")  # DL6SC1234 fits both


def canonical_plate(raw):
    """Return (canonical plate, format) for any written form of a plate.
    The plate is None when the text is empty or does not parse."""
    s = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    if not s:
        return None, "EMPTY"
    if BH.fullmatch(s):
        return s, "BH"
    m = DELHI.fullmatch(s)
    if m:
        return f"DL{int(m.group(1))}{m.group(2)}{m.group(3)}", "DELHI"
    m = STANDARD.fullmatch(s)
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}{m.group(3)}{m.group(4)}", "STANDARD"
    return None, "INVALID_FORMAT"


if __name__ == "__main__":
    import doctest
    print(doctest.testmod())
