s = '9' * 81 #make string

while s.find('33333') != -1 or s.find('999') != -1:
    if s.find('33333') != -1:
        s = s.replace('33333', '99', 1)
    else:
        s = s.replace('999', '3', 1)

print(s)