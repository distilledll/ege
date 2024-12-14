from itertools import *

s = "457 46 567 12 136 235 13".split()
v = "fe ec ca ab bd df fg dg gc".split()
print(*range(1, 8))
for p in permutations('abcdefg'):
    if all(str(p.index(b) + 1) in s[p.index(a)] for a, b in v):
        print(*p)
