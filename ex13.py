"""
mask: 11111111.11111111.11111|000.00000000
net:  10101100.00010000.10101|000.00000000
2^11 вариантов IP
"""

from itertools import *

def summ(a):
    r = 0
    for i in a:
        r += int(i)

    return r

ans = 0
for p in product((0, 1), repeat=11):
    if (summ(p) + 8) % 5 != 0:
        ans += 1

print(ans)