def f(x):
    res = ''
    while x > 0:
        res = str(x % 2) + res #заменить (2) на нужную сс
        x //= 2
    return res #string


for n in range(1, 13): #по условию
    x = f(n)
    if n % 2 == 0:
        x = '10' + x
    else:
        x = '1' + x + '01'
    r = int(x, 2)
    print(r)
