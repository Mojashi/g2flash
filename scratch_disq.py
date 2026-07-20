import sys
from capstone import *
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True
def load(path):
    return open(path,'rb').read()
OLD='g2_2.2.4.34.bin'; NEW='g2_2.2.6.10.bin'
def disasm(path, addr, n, base):
    data=load(path)
    foff=(addr & ~1) - base if 'OLD' in path or path==OLD else addr-base
    # we will pass explicit
    pass
def dis(path, addr, count, clearbit):
    data=load(path)
    if clearbit:
        foff=(addr & ~1)-0x39E680
    else:
        foff=addr-0x39E680
    code=data[foff:foff+count*2+8]
    runaddr=addr & ~1
    for i in md.disasm(code, runaddr):
        print("0x%08x: %-10s %s"%(i.address, i.mnemonic, i.op_str))
        count-=1
        if count<=0: break

if __name__=='__main__':
    path=sys.argv[1]; addr=int(sys.argv[2],16); count=int(sys.argv[3]); clearbit=int(sys.argv[4])
    dis(path,addr,count,clearbit)
