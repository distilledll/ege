s = '123456789ABCDEFGHI'
for x in s:
    f = int(f'98897{x}21', 19) + int(f'2{x}923', 19)
#    if f % 18 == 0:
#        print(x, f // 18)

#OR

s = 3 * 3125**8 + 2 * 625**7 - 4 * 625**6 + 3 * 125**5 - 5 * 25**4 - 2025
c = 0
while s > 0:
    if s % 25 == 0:
        c += 1
    s //= 25
#print(c)

#OR

for x in range(2030):
    f = 7**170 + 7**100 - x
    c = 0
    while f > 0:
        if f % 7 == 0:
            c += 1
        f //= 7
    if c == 71:
        print(x)