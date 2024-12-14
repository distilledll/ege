from itertools import *

for x, y, z, w in product((0, 1), repeat=4):
    print(x, y, z, w, bool((not(not w or y) or x) or not z))

"""
x y z w
0 0 1 0 False
0 1 1 0 False
0 1 1 1 False

zywx
"""