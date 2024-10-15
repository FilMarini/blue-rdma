import random
import copy
from bitstring import BitStream as BS
from cocotbext.axi import AxiStreamBus, AxiStreamSource, AxiStreamSink, AxiStreamFrame
from TestUtils import *

def dmaPyServer(initiator, sqpn, startAddr, pktLen, wrId):
    dmaRCResps = []
    dmaRCResp = DmaReadCltRespTransaction()
    dmaRCResp.initiator = initiator
    dmaRCResp.sqpn = sqpn
    dmaRCResp.wr_id = wrId
    dmaRCResp.is_resp_err = 0
    numberOfFullPkts = int(pktLen / DMA_DS_BYTEEN_B)
    remainingBytes = pktLen % DMA_DS_BYTEEN_B
    isFirstBS = BS(uint = 1, length = DMA_DS_ISFIRST_B)
    isLastBS = BS(uint = 0, length = DMA_DS_ISLAST_B)
    for pktNum in range(numberOfFullPkts):
        if (pktNum + 1 == numberOfFullPkts and remainingBytes == 0):
            isLastBS = BS(uint = 1, length = DMA_DS_ISLAST_B)
        dataBS = BS(uint = int.from_bytes(random.randbytes(DMA_DS_BYTEEN_B), "big"), length = DMA_DS_DATA_B)
        byteEnBS = BS(DMA_DS_BYTEEN_B)
        byteEnBS.set(1)
        dataStreamBS = BS()
        dataStreamBS.append(dataBS)
        dataStreamBS.append(byteEnBS)
        dataStreamBS.append(isFirstBS)
        dataStreamBS.append(isLastBS)
        dmaRCResp.data_stream = dataStreamBS.uint
        dmaRCResps.append(copy.deepcopy(dmaRCResp))
        isFirstBS = BS(uint = 0, length = DMA_DS_ISFIRST_B)
    if remainingBytes != 0:
        isLastBS = BS(uint = 1, length = DMA_DS_ISLAST_B)
        dataBS = BS(DMA_DS_DATA_B)
        dataRemBS = BS(uint = int.from_bytes(random.randbytes(remainingBytes), "big"), length = remainingBytes * 8)
        dataBS.overwrite(dataRemBS, pos = 0)
        byteEnBS = BS(DMA_DS_BYTEEN_B)
        byteEnRemBS = BS(remainingBytes)
        byteEnRemBS.set(1)
        byteEnBS.overwrite(byteEnRemBS, pos = 0)
        dataStreamBS = BS()
        dataStreamBS.append(dataBS)
        dataStreamBS.append(byteEnBS)
        dataStreamBS.append(isFirstBS)
        dataStreamBS.append(isLastBS)
        dmaRCResp.data_stream = dataStreamBS.uint
        dmaRCResps.append(dmaRCResp)
    return dmaRCResps

