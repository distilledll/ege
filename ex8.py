from itertools import *

s = '0123456789ABCD' #14 ss
r = 0
for i in product(s, repeat=5):
    if i[0] != '0': #and other if
        r += 1
print(r)

#OR

s = 'Ф О К У С'.split()
s = sorted(s)
r = 0
for i in product(s, repeat=5):
    r += 1
    if i.count('Ф') == 0 and i.count('У') == 2:
        print(r, i)

#OR

v = '012345678'
r = 0
for i in product(v, repeat=6):
    if i[0] not in '01357' and i[-1] not in '23' and i.count('1') >= 2:
        print(i)
        r += 1
print(r)