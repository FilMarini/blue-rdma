import re
import sys
import math

assert len(sys.argv) == 2, "Usage: python3 TestBlueAll.py ROOT_DIRECTORY"
rootDir = sys.argv[1]

settingsFile = f'{rootDir}/src/Settings.bsv'
pythonSettingsFile = f'{rootDir}/test/cocotb/BSVSettings.py'

def convertVal(line):
    elem = None
    value = None
    if not line.startswith('//'):
        lineSplit = re.split(r' \s*(?![^()]*\))', line.strip().replace(';',''))
        if 'typedef' in lineSplit:
            elem = lineSplit[2]
            value = lineSplit[1]
    return elem, value

def getValue(elem):
    for finElem in finElems:
        if elem == finElem[0]:
            return finElem[1]

def getOp(elem):
    op = elem.split('#')[0]
    finOpVals = []
    opValTog = re.findall(r'\(.*?\)', elem)[0]
    opValTog = opValTog.replace('(', '').replace(')', '')
    opVals = opValTog.split(', ')
    for opVal in opVals:
        if opVal.isnumeric():
            finOpVals.append(int(opVal))
        else:
            finOpVals.append(getValue(opVal))
    match op:
        case 'TMul':
            return (int(finOpVals[0] * finOpVals[1]))
        case 'TDiv':
            return (int(finOpVals[0] / finOpVals[1]))
        case 'TExp':
            return (f'1 << {finOpVals[0]}')

with open(settingsFile) as f:
    lines = f.readlines()
elems = []
finElems = []
for line in lines:
    elem, value = convertVal(line)
    if elem:
        elems.append([elem, value])
for elem in elems:
    if elem[1].isnumeric():
        finElems.append([elem[0], int(elem[1])])
for elem in elems:
    if not elem[1].isnumeric():
        if not '#' in elem[1]:
            finElems.append([elem[0], getValue(elem[1])])
        if '#' in elem[1]:
            finElems.append([elem[0], getOp(elem[1])])

with open(pythonSettingsFile, "w") as p:
    p.write('# This is an autogenerated file. Do not edit!\n')
    for finElem in finElems:
        p.write(f'{finElem[0]} = {finElem[1]}\n')

