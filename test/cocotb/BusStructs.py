from bitstring import BitStream as BS
from TestUtils import *

# QP
class respQp:
    def __init__(self, metaRespBus):
        self.qpiSqSigAll = get_bool(metaRespBus, 0)
        self.qpiType = slice_vec(metaRespBus, 4, 1)
        self.qpaRnrRetry = slice_vec(metaRespBus, 7, 5)
        self.qpaRetryCnt = slice_vec(metaRespBus, 10, 8)
        self.qpaTimeOut = slice_vec(metaRespBus, 15, 11)
        self.qpaRnrTimer = slice_vec(metaRespBus, 20, 16)
        self.qpaMaxDestReadAtomic = slice_vec(metaRespBus, 28, 21)
        self.qpaMaxReadAtomic = slice_vec(metaRespBus, 36, 29)
        self.qpaSqDraining = get_bool(metaRespBus, 37)
        self.qpaPKey = slice_vec(metaRespBus, 53, 38)
        self.qpaCap = slice_vec(metaRespBus, 93, 54)
        self.qpaAccFlags = slice_vec(metaRespBus, 101, 94)
        self.qpaDqpn = slice_vec(metaRespBus, 125, 102)
        self.qpaSqpsn = slice_vec(metaRespBus, 149, 126)
        self.qpaRqpsn = slice_vec(metaRespBus, 173, 150)
        self.qpaQKey = slice_vec(metaRespBus, 205, 174)
        self.qpaPmtu = slice_vec(metaRespBus, 208, 206)
        self.qpaCurrQpState = slice_vec(metaRespBus, 212, 209)
        self.qpaQpState =  slice_vec(metaRespBus, 216, 213)
        self.pdHandler = slice_vec(metaRespBus, 248, 217)
        self.qpn = slice_vec(metaRespBus, 272, 249)
        self.successOrNot = get_bool(metaRespBus, 273)
        self.busType = slice_vec(metaRespBus, 275, 274)

class reqQp:
    def __init__(self, **kwargs):
        self.qpReqType            = BS(uint = random.getrandbits(QP_REQTYPE_B), length = (QP_REQTYPE_B))
        self.pdHandler            = BS(uint = random.getrandbits(QP_PDHANDLER_B), length = (QP_PDHANDLER_B))
        self.qpn                  = BS(uint = random.getrandbits(QP_QPN_B), length = (QP_QPN_B))
        self.qpAttrMask           = BS(uint = random.getrandbits(QP_ATTRMASK_B), length = (QP_ATTRMASK_B))
        self.qpaQpState           = BS(uint = random.getrandbits(QPA_QPSTATE_B), length = (QPA_QPSTATE_B))
        self.qpaCurrQpState       = BS(uint = random.getrandbits(QPA_QPSTATE_B), length = (QPA_QPSTATE_B))
        self.qpaPmtu              = BS(uint = random.getrandbits(QPA_PMTU_B), length = (QPA_PMTU_B))
        self.qpaQKey              = BS(uint = random.getrandbits(QPA_QKEY_B), length = (QPA_QKEY_B))
        self.qpaRqPsn             = BS(uint = random.getrandbits(QPA_RQPSN_B), length = (QPA_RQPSN_B))
        self.qpaSqPsn             = BS(uint = random.getrandbits(QPA_SQPSN_B), length = (QPA_SQPSN_B))
        self.qpaDqpn              = BS(uint = random.getrandbits(QPA_DQPN_B), length = (QPA_DQPN_B))
        self.qpaAccFlags          = BS(uint = random.getrandbits(QPA_QPACCFLAGS_B), length = (QPA_QPACCFLAGS_B))
        self.qpaCap               = BS(uint = random.getrandbits(QPA_CAP_B), length = (QPA_CAP_B))
        self.qpaPKey              = BS(uint = random.getrandbits(QPA_PKEY_B), length = (QPA_PKEY_B))
        self.qpaSqDraining        = BS(uint = random.getrandbits(QPA_SQDRAINING_B), length = QPA_SQDRAINING_B)
        self.qpaMaxReadAtomic     = BS(uint = random.getrandbits(QPA_MAXREADATOMIC_B), length = (QPA_MAXREADATOMIC_B))
        self.qpaMaxDestReadAtomic = BS(uint = random.getrandbits(QPA_MAXDESTREADATOMIC_B), length = (QPA_MAXDESTREADATOMIC_B))
        self.qpaRnrTimer          = BS(uint = random.getrandbits(QPA_RNRTIMER_B), length = (QPA_RNRTIMER_B))
        self.qpaTimeOut           = BS(uint = random.getrandbits(QPA_TIMEOUT_B), length = (QPA_TIMEOUT_B))
        self.qpaRetryCnt          = BS(uint = random.getrandbits(QPA_RETRYCNT_B), length = (QPA_RETRYCNT_B))
        self.qpaRnrRetry          = BS(uint = random.getrandbits(QPA_RNRRETRY_B), length = (QPA_RNRRETRY_B))
        self.qpiType              = BS(uint = random.getrandbits(QPI_TYPE_B), length = (QPI_TYPE_B))
        self.qpiSqSigAll          = BS(uint = random.getrandbits(QPI_SQSIGALL_B), length = (QPI_SQSIGALL_B))
        for key, value in kwargs.items():
            setattr(self, key, value)

    def getBus(self):
        metaBus = BS()
        metaBus.append(self.qpReqType)
        metaBus.append(self.pdHandler)
        metaBus.append(self.qpn)
        metaBus.append(self.qpAttrMask)
        metaBus.append(self.qpaQpState)
        metaBus.append(self.qpaCurrQpState)
        metaBus.append(self.qpaPmtu)
        metaBus.append(self.qpaQKey)
        metaBus.append(self.qpaRqPsn)
        metaBus.append(self.qpaSqPsn)
        metaBus.append(self.qpaDqpn)
        metaBus.append(self.qpaAccFlags)
        metaBus.append(self.qpaCap)
        metaBus.append(self.qpaPKey)
        metaBus.append(self.qpaSqDraining)
        metaBus.append(self.qpaMaxReadAtomic)
        metaBus.append(self.qpaMaxDestReadAtomic)
        metaBus.append(self.qpaRnrTimer)
        metaBus.append(self.qpaTimeOut)
        metaBus.append(self.qpaRetryCnt)
        metaBus.append(self.qpaRnrRetry)
        metaBus.append(self.qpiType)
        metaBus.append(self.qpiSqSigAll)
        fullBus = BS(META_DATA_BITS - metaBus.length)
        fullBus.append(metaBus)
        fullBus.overwrite(BS(uint = METADATA_QP_T, length = 2), pos = 0)
        return fullBus

    def getBusValue(self):
        fullBus = self.getBus()
        return fullBus.uint

    def setAttr(self, attrBus):
        self.qpaRnrRetry = slice_vec(attrBus, 2, 0)
        self.qpaRetryCnt = slice_vec(attrBus, 5, 3)
        self.qpaTimeOut = slice_vec(attrBus, 10, 6)
        self.qpaRnrTimer = slice_vec(attrBus, 15, 11)
        self.qpaMaxDestReadAtomic = slice_vec(attrBus, 23, 16)
        self.qpaMaxReadAtomic = slice_vec(attrBus, 31, 24)
        self.qpaSqDraining = slice_vec(attrBus, 32, 32)
        self.qpaPKey = slice_vec(attrBus, 48, 33)
        self.qpaCap = slice_vec(attrBus, 88, 49)
        self.qpaAccFlags = slice_vec(attrBus, 96, 89)
        self.qpaDqpn = slice_vec(attrBus, 120, 97)
        self.qpaSqPsn = slice_vec(attrBus, 144, 121)
        self.qpaRqPsn = slice_vec(attrBus, 168, 145)
        self.qpaQKey = slice_vec(attrBus, 200, 169)
        self.qpaPmtu = slice_vec(attrBus, 203, 201)
        self.qpaCurrQpState = slice_vec(attrBus, 207, 204)
        self.qpaQpState = slice_vec(attrBus, 211, 208)

    def setInitAttr(self, initAttrBus):
        self.qpiType     = slice_vec(initAttrBus, 4, 1)
        self.qpiSqSigAll = slice_vec(initAttrBus, 0, 0)

    def mkSimQpAttr(self, pmtu_value, qpState=random.getrandbits(QPA_QPSTATE_B),
                    dqpn_value=random.getrandbits(QPA_DQPN_B), setExpectedPsnAsNextPsn = True,
                    setZero2ExpectedPsnAndNextPsn = True):
        epsn_tmp = random.getrandbits(QPA_RQPSN_B)
        npsn_tmp = random.getrandbits(QPA_SQPSN_B)
        if setExpectedPsnAsNextPsn:
            epsn_tmp = npsn_tmp
        if setZero2ExpectedPsnAndNextPsn:
            epsn_tmp = 0
            npsn_tmp = 0
        qpAccessFlags_value = 0x0E # access_remote_write, access_remote_read, access_remote_atomic
        cap_value = 0x2020010100 # line 1145 file Utils4Test.bsv # TODO create single fields

        self.qpaQpState           = BitStream(uint = qpState, length = QPA_QPSTATE_B)
        self.qpaPmtu              = BitStream(uint = pmtu_value, length = QPA_PMTU_B)
        self.qpaRqPsn             = BitStream(uint = epsn_tmp, length = QPA_RQPSN_B)
        self.qpaSqPsn             = BitStream(uint = npsn_tmp, length = QPA_SQPSN_B)
        self.qpaDqpn              = BitStream(uint = dqpn_value, length = QPA_DQPN_B)
        self.qpaQpAccessFlags     = BitStream(uint = qpAccessFlags_value, length = QPA_QPACCFLAGS_B)
        self.qpaCap               = BitStream(uint = cap_value, length = QPA_CAP_B)
        self.qpaSqDraining        = BitStream(uint = False, length = QPA_SQDRAINING_B)
        self.qpaMaxReadAtomic     = BitStream(uint = MAX_QP_RD_ATOM, length = QPA_MAXREADATOMIC_B)
        self.qpaMaxDestReadAtomic = BitStream(uint = MAX_QP_DST_RD_ATOM, length = QPA_MAXDESTREADATOMIC_B)
        self.qpaRnrTimer          = BitStream(uint = 1, length = QPA_RNRTIMER_B)
        self.qpaTimeOut           = BitStream(uint = 1, length = QPA_TIMEOUT_B)
        self.qpaRetryCnt          = BitStream(uint = DEFAULT_RETRY_NUM, length = QPA_RETRYCNT_B)
        self.qpaRnrRetry          = BitStream(uint = DEFAULT_RETRY_NUM, length = QPA_RNRRETRY_B)

# MR
class respMr:
    def __init__(self, metaRespBus):
        self.rKey         = slice_vec(metaRespBus, 31, 0)
        self.lKey         = slice_vec(metaRespBus, 63, 32)
        self.mrRKeyPart   = slice_vec(metaRespBus, 88, 64)
        self.mrLKeyPart   = slice_vec(metaRespBus, 113, 89)
        self.mrPdHandler  = slice_vec(metaRespBus, 145, 114)
        self.mrAccFlags   = slice_vec(metaRespBus, 153, 146)
        self.mrLen        = slice_vec(metaRespBus, 185, 154)
        self.mrLAddr      = slice_vec(metaRespBus, 249, 186)
        self.successOrNot = get_bool(metaRespBus, 250)
        self.busType      = slice_vec(metaRespBus, 275, 274)

class reqMr:
    def __init__(self, **kwargs):
        self.allocOrNot  = BS(uint = random.getrandbits(MR_ALLOC_OR_NOT_B), length = (MR_ALLOC_OR_NOT_B))
        self.mrLAddr     = BS(uint = random.getrandbits(MR_LADDR_B), length = (MR_LADDR_B))
        self.mrLen       = BS(uint = random.getrandbits(MR_LEN_B), length = (MR_LEN_B))
        self.mrAccFlags  = BS(uint = random.getrandbits(MR_ACCFLAGS_B), length = (MR_ACCFLAGS_B))
        self.mrPdHandler = BS(uint = random.getrandbits(MR_PDHANDLER_B), length = (MR_PDHANDLER_B))
        self.mrLKeyPart  = BS(uint = random.getrandbits(MR_LKEYPART_B), length = (MR_LKEYPART_B))
        self.mrRKeyPart  = BS(uint = random.getrandbits(MR_RKEYPART_B), length = (MR_RKEYPART_B))
        self.lKeyOrNot   = BS(uint = random.getrandbits(MR_LKEYORNOT_B), length = (MR_LKEYORNOT_B))
        self.lKey        = BS(uint = random.getrandbits(MR_LKEY_B), length = (MR_LKEY_B))
        self.rKey        = BS(uint = random.getrandbits(MR_RKEY_B), length = (MR_RKEY_B))
        for key, value in kwargs.items():
            setattr(self, key, value)

    def getBus(self):
        metaBus = BS()
        metaBus.append(self.allocOrNot)
        metaBus.append(self.mrLAddr)
        metaBus.append(self.mrLen)
        metaBus.append(self.mrAccFlags)
        metaBus.append(self.mrPdHandler)
        metaBus.append(self.mrLKeyPart)
        metaBus.append(self.mrRKeyPart)
        metaBus.append(self.lKeyOrNot)
        metaBus.append(self.lKey)
        metaBus.append(self.rKey)
        fullBus = BS(META_DATA_BITS - metaBus.length)
        fullBus.append(metaBus)
        fullBus.overwrite(BS(uint = METADATA_MR_T, length = 2), pos = 0)
        return fullBus

    def getBusValue(self):
        fullBus = self.getBus()
        return fullBus.uint

# PD
class respPd:
    def __init__(self, metaRespBus):
        self.pdKey        = slice_vec(metaRespBus, PD_KEY_B - 1, 0)
        self.pdHandler    = slice_vec(metaRespBus, PD_KEY_B + PD_HANDLER_B - 1, PD_KEY_B)
        self.successOrNot = get_bool(metaRespBus, PD_KEY_B + PD_HANDLER_B)
        self.busType      = slice_vec(metaRespBus, 275, 274)

class reqPd:
    def __init__(self, **kwargs):
        self.allocOrNot = BS(uint = random.getrandbits(PD_ALLOC_OR_NOT_B), length = (PD_ALLOC_OR_NOT_B))
        self.pdKey      = BS(uint = random.getrandbits(PD_KEY_B), length = (PD_KEY_B))
        self.pdHandler  = BS(uint = random.getrandbits(PD_HANDLER_B), length = (PD_HANDLER_B))
        for key, value in kwargs.items():
            setattr(self, key, value)

    def getBus(self):
        metaBus = BS()
        metaBus.append(self.allocOrNot)
        metaBus.append(self.pdKey)
        metaBus.append(self.pdHandler)
        fullBus = BS(META_DATA_BITS - metaBus.length)
        fullBus.append(metaBus)
        fullBus.overwrite(BS(uint = METADATA_PD_T, length = 2), pos = 0)
        return fullBus

    def getBusValue(self):
        fullBus = self.getBus()
        return fullBus.uint

# DMA Read
class reqDmaRead:
    def __init__(self, dmaReadReqBus):
        self.initiator = slice_vec(dmaReadReqBus, 168, 165)
        self.sqpn      = slice_vec(dmaReadReqBus, 164, 141)
        self.startAddr = slice_vec(dmaReadReqBus, 140, 77)
        self.pktLen    = slice_vec(dmaReadReqBus, 76, 64)
        self.wrId      = slice_vec(dmaReadReqBus, 63, 0)
