"""DMD Mining: every pool mining DMD (the DebitMyData coin), live.

It follows each pool through its own API (its hashrate, miners, fees, ports, its blocks' status)
and the chain (who found each block, as DMD Stats names them from DebitMyData's pool list), keeps
their history, sends the notifications each device chose, and writes the files of the public site
(mining.debitmydata.io), which are its API too.
"""

__version__ = "1.0.4"
